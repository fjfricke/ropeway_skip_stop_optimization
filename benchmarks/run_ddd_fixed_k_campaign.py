from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from time import perf_counter
from typing import Any

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_campaign import (
    DddFixedKCampaignConfig,
    derive_available_fleet_intervals,
    derive_skip_stop_benefit_interval,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddAnalyticAllStopInfeasible,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_root_cg_application import (
    run_namespace,
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
    DddFixedKOperatingMode,
    DddFixedKProfileConfig,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run certified exact-K fixed-start trajectory Root-CG campaigns."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("benchmarks/output/ddd_fixed_k_campaigns"),
    )
    parser.add_argument(
        "--frontend-root",
        type=Path,
        default=Path("frontend/public/generated/optimization"),
    )
    parser.add_argument("--frontend-live", action="store_true")
    parser.add_argument("--progress", action="store_true")
    parser.add_argument(
        "--verbose-progress",
        action="store_true",
        help="Show the full per-round solver diagnostics.",
    )
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    config = DddFixedKCampaignConfig.from_dict(
        json.loads(args.config.read_text(encoding="utf-8"))
    )
    profile = DddFixedKProfileConfig.for_profile(config.profile)
    profile.validate()
    campaign_dir = args.output_root / config.campaign_id
    store = OptimizationLiveStore(
        OptimizationLivePaths(
            canonical_campaign_dir=campaign_dir,
            frontend_root=args.frontend_root if args.frontend_live else None,
        )
    )
    existing_events = store.read_events()
    if existing_events and not args.resume:
        raise ValueError(
            f"campaign {config.campaign_id!r} already exists; use --resume or "
            "choose a new campaign_id"
        )
    completed: list[dict[str, Any]] = []
    completed_keys: set[tuple[str, int]] = set()
    if existing_events:
        snapshot = reduce_optimization_events(existing_events)
        for trial in snapshot["trials"].values():
            if trial["status"] != "complete":
                continue
            completed.append(dict(trial))
            completed_keys.add(
                (str(trial["policy_id"]), int(trial["available_fleet_count"]))
            )
    else:
        store.append_new(
            OptimizationEventKind.CAMPAIGN_STARTED,
            config.campaign_id,
            payload={
                "label": config.label,
                "objective": config.objective.value,
                "example_id": config.example_id,
                "profile": config.profile.value,
                "start_policy": config.start_policy.value,
                "trial_count": len(config.k_values) * len(config.operating_modes),
                "method": "certified_fixed_k_trajectory_root_cg",
            },
        )
        _publish(store)

    for operating_mode in config.operating_modes:
        for cabin_count in config.k_values:
            policy_id = operating_mode.value
            if (policy_id, cabin_count) in completed_keys:
                continue
            trial_dir = campaign_dir / "policies" / policy_id / f"k{cabin_count}"
            checkpoint_path = trial_dir / "checkpoint.json"
            fingerprint = _trial_fingerprint(config, operating_mode, cabin_count)
            store.append_new(
                OptimizationEventKind.TRIAL_STARTED,
                config.campaign_id,
                policy_id=policy_id,
                available_fleet_count=cabin_count,
                trial_fingerprint=fingerprint,
                stage="setup",
                payload={"exact_active_cabin_count": cabin_count},
            )
            _publish(store)
            namespace = _trial_namespace(
                config=config,
                profile=profile,
                operating_mode=operating_mode,
                cabin_count=cabin_count,
                trial_dir=trial_dir,
                checkpoint_path=checkpoint_path,
                resume=args.resume and checkpoint_path.exists(),
                progress=args.progress,
                verbose_progress=args.verbose_progress,
            )
            trial_started = perf_counter()

            def on_round(iteration: Any) -> None:
                store.append_new(
                    OptimizationEventKind.CG_ROUND_COMPLETED,
                    config.campaign_id,
                    policy_id=policy_id,
                    available_fleet_count=cabin_count,
                    trial_fingerprint=fingerprint,
                    stage="root_column_generation",
                    round_index=iteration.round_index,
                    global_certified_lower_bound=iteration.global_lower_bound,
                    global_validated_upper_bound=iteration.global_upper_bound,
                    global_relative_gap=(
                        None
                        if iteration.global_upper_bound is None
                        else max(
                            0.0,
                            iteration.global_upper_bound
                            - iteration.global_lower_bound,
                        )
                        / max(abs(iteration.global_upper_bound), 1e-9)
                    ),
                    local_solver_incumbent=(
                        iteration.restricted_integer_upper_bound
                    ),
                    local_solver_bound=iteration.restricted_lp_value,
                    elapsed_seconds=perf_counter() - trial_started,
                    payload={
                        "restricted_lp_value": iteration.restricted_lp_value,
                        "pricing_tier_seconds": iteration.pricing_tier_seconds,
                        "pricing_retry_count": iteration.pricing_retry_count,
                        "unresolved_pricing_count": iteration.unresolved_pricing_count,
                        "trajectory_count": iteration.trajectory_count,
                        "incompatibility_pair_count": (
                            iteration.incompatibility_pair_count
                        ),
                        "restricted_mip_ran": iteration.restricted_mip_ran,
                        "restricted_mip_solution_count": (
                            iteration.restricted_mip_solution_count
                        ),
                        "restricted_integer_upper_bound": (
                            iteration.restricted_integer_upper_bound
                        ),
                        "primal_pricing_call_count": (
                            iteration.primal_pricing_call_count
                        ),
                        "primal_pricing_seconds": iteration.primal_pricing_seconds,
                        "primal_pricing_candidate_count": (
                            iteration.primal_pricing_candidate_count
                        ),
                        "primal_pricing_status_counts": dict(
                            iteration.primal_pricing_status_counts
                        ),
                        "remaining_budget_seconds": (
                            iteration.remaining_budget_seconds
                        ),
                    },
                )
                _publish(store)

            try:
                raw = run_namespace(namespace, progress_hook=on_round)
                payload = dict(raw["payload"])
            except DddAnalyticAllStopInfeasible as error:
                payload = {
                    "status": "movement_infeasible",
                    "certificate_kind": "analytic_all_stop_capacity",
                    "detail": str(error),
                    "case_id": config.example_id,
                    "operating_mode": operating_mode.value,
                    "cabin_count": cabin_count,
                    "objective": config.objective.value,
                    "fixed_start_policy": config.start_policy.value,
                    "all_stop_maximum_cabin_count": error.maximum_cabin_count,
                    "total_seconds": perf_counter() - trial_started,
                }
                completed.append(payload)
                store.append_new(
                    OptimizationEventKind.TRIAL_COMPLETED,
                    config.campaign_id,
                    policy_id=policy_id,
                    available_fleet_count=cabin_count,
                    trial_fingerprint=fingerprint,
                    stage="analytic_all_stop_capacity",
                    elapsed_seconds=float(payload["total_seconds"]),
                    payload=payload,
                )
                _publish(store)
                print(
                    f"{operating_mode.value} K={cabin_count} "
                    "status=movement_infeasible analytic K_max_AS="
                    f"{error.maximum_cabin_count}",
                    flush=True,
                )
                continue
            except Exception as error:
                store.append_new(
                    OptimizationEventKind.TRIAL_FAILED,
                    config.campaign_id,
                    policy_id=policy_id,
                    available_fleet_count=cabin_count,
                    trial_fingerprint=fingerprint,
                    stage="failed",
                    payload={"detail": str(error)},
                )
                _publish(store)
                raise
            completed.append(payload)
            store.append_new(
                OptimizationEventKind.TRIAL_COMPLETED,
                config.campaign_id,
                policy_id=policy_id,
                available_fleet_count=cabin_count,
                trial_fingerprint=fingerprint,
                stage="complete",
                global_certified_lower_bound=float(payload["certified_lower_bound"]),
                global_validated_upper_bound=(
                    None
                    if payload["best_upper_bound"] is None
                    else float(payload["best_upper_bound"])
                ),
                global_relative_gap=(
                    None
                    if payload["relative_gap"] is None
                    else float(payload["relative_gap"])
                ),
                elapsed_seconds=float(payload["total_seconds"]),
                payload=payload,
            )
            _publish(store)

    comparison = _derive_comparisons(config, completed)
    store.append_new(
        OptimizationEventKind.CAMPAIGN_COMPLETED,
        config.campaign_id,
        payload={
            "status": "complete",
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "comparison": comparison,
        },
    )
    _publish(store)
    print(
        f"campaign={config.campaign_id} status=complete "
        f"trials={len(completed)}/{len(config.k_values) * len(config.operating_modes)} "
        f"output={store.paths.campaign_path}"
    )


def _trial_namespace(
    *,
    config: DddFixedKCampaignConfig,
    profile: DddFixedKProfileConfig,
    operating_mode: DddFixedKOperatingMode,
    cabin_count: int,
    trial_dir: Path,
    checkpoint_path: Path,
    resume: bool,
    progress: bool,
    verbose_progress: bool,
) -> argparse.Namespace:
    return argparse.Namespace(
        example=config.example_id,
        fleet_mode="fixed_starts",
        cabins=cabin_count,
        horizon=250.0,
        warmup_seconds=0.0,
        reservoir_entry_state=None,
        reservoir_entry_resource=[],
        reservoir_boundary_mode="ideal_non_limiting",
        reservoir_dispatch_resource=[],
        reservoir_first_route=[],
        dispatch_cardinality="exact",
        force_all_stop=operating_mode is DddFixedKOperatingMode.ALL_STOP,
        objective=config.objective.value,
        max_iterations=profile.max_iterations,
        total_time_limit=profile.total_time_limit_seconds,
        pricing_time_limit=profile.pricing_time_limit_tiers_seconds[0],
        pricing_time_limit_tier=list(profile.pricing_time_limit_tiers_seconds),
        fixed_k_certified=True,
        fixed_start_policy=config.start_policy.value,
        cp_seed_time_limit=profile.cp_seed_time_limit_seconds,
        cp_seed_workers=1,
        restricted_mip_interval=profile.restricted_mip_interval,
        restricted_mip_time_limit=profile.restricted_mip_time_limit_seconds,
        final_mip_time_limit=profile.final_mip_time_limit_seconds,
        objective_floor=0.0,
        waiting_step_seconds=1.0,
        pricing_threads=1,
        master_dual_mode="default",
        proof_pricing_mip_focus=2,
        extra_pricing_mip_focus=1,
        pricing_formulation="time_expanded_path",
        max_pair_checks=2_000_000,
        conflict_row_mode="pair_only",
        max_resource_window_rounds=100,
        columns_per_cabin_per_round=1,
        diversity_mode="off",
        minimum_diversity_distance=1,
        extra_column_time_limit=10.0,
        coordinated_primal_time_limit=(
            config.coordinated_primal_time_limit_seconds
            if operating_mode is DddFixedKOperatingMode.SKIP_STOP
            else 0.0
        ),
        coordinated_primal_interval=config.coordinated_primal_interval,
        coordinated_primal_workers=config.coordinated_primal_workers,
        coordinated_primal_candidates=(
            config.coordinated_primal_candidate_count
        ),
        coordinated_primal_max_preferences=(
            config.coordinated_primal_maximum_preference_count
        ),
        oip_primal_pricing_time_limit=0.0,
        reservoir_primal_pricing_time_limit=0.0,
        reservoir_primal_pricing_mode="compact_dispatch_windows",
        reservoir_primal_max_cabin_calls=1,
        reservoir_dispatch_anchor_count=1,
        reservoir_primal_max_arcs=1,
        reservoir_primal_max_passenger_arc_product=1,
        solver_output=False,
        no_progress=not progress,
        verbose_progress=verbose_progress,
        output_dir=trial_dir,
        checkpoint_path=checkpoint_path,
        resume_checkpoint=checkpoint_path if resume else None,
        neighbor_k_checkpoint=None,
        no_checkpoint=False,
    )


def _trial_fingerprint(
    config: DddFixedKCampaignConfig,
    operating_mode: DddFixedKOperatingMode,
    cabin_count: int,
) -> str:
    payload = {
        **asdict(config),
        "operating_mode": operating_mode.value,
        "cabin_count": cabin_count,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


def _derive_comparisons(
    config: DddFixedKCampaignConfig,
    payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    by_mode: dict[str, dict[int, tuple[float, float | None]]] = {}
    for payload in payloads:
        if payload.get("certified_lower_bound") is None:
            continue
        by_mode.setdefault(str(payload["operating_mode"]), {})[
            int(payload["cabin_count"])
        ] = (
            float(payload["certified_lower_bound"]),
            (
                None
                if payload["best_upper_bound"] is None
                else float(payload["best_upper_bound"])
            ),
        )
    available = {
        mode: {
            str(k): {"lower_bound": bounds[0], "upper_bound": bounds[1]}
            for k, bounds in derive_available_fleet_intervals(values).items()
        }
        for mode, values in by_mode.items()
    }
    benefit: dict[str, dict[str, float]] = {}
    all_stop = by_mode.get(DddFixedKOperatingMode.ALL_STOP.value, {})
    skip_stop = by_mode.get(DddFixedKOperatingMode.SKIP_STOP.value, {})
    for cabin_count in sorted(set(all_stop) & set(skip_stop)):
        as_lower, as_upper = all_stop[cabin_count]
        ss_lower, ss_upper = skip_stop[cabin_count]
        if as_upper is None or ss_upper is None:
            continue
        lower, upper = derive_skip_stop_benefit_interval(
            all_stop_lower=as_lower,
            all_stop_upper=as_upper,
            skip_stop_lower=ss_lower,
            skip_stop_upper=ss_upper,
        )
        benefit[str(cabin_count)] = {"lower_bound": lower, "upper_bound": upper}
    return {
        "available_fleet_intervals": available,
        "skip_stop_benefit_intervals": benefit,
    }


def _publish(store: OptimizationLiveStore) -> None:
    store.publish(reduce_optimization_events(store.read_events()))


if __name__ == "__main__":
    main()
