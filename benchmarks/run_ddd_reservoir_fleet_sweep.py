from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from ropeway_skip_stop_optimization.benchmarking.ddd_fleet_sweep import (
    DddFleetPolicyConfig,
    DddFleetSweepConfig,
    DddFleetSweepRunner,
    DddFleetTrialResult,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_root_cg import (
    DddRootCgTrialConfig,
    DddRootCgTrialRunner,
)
from ropeway_skip_stop_optimization.benchmarking.optimization_live_store import (
    OptimizationLivePaths,
    OptimizationLiveStore,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a fixed-K DDD reservoir fleet sweep")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("benchmarks/output/ddd_fleet_sweeps"),
    )
    parser.add_argument(
        "--frontend-root",
        type=Path,
        default=Path("frontend/public/generated/optimization"),
    )
    parser.add_argument("--frontend-live", action="store_true")
    parser.add_argument("--progress", action="store_true")
    parser.add_argument(
        "--total-time-limit",
        type=float,
        help="Explicitly replace the cumulative per-K budget from the config.",
    )
    args = parser.parse_args()
    raw = json.loads(args.config.read_text(encoding="utf-8"))
    config = DddFleetSweepConfig.from_dict(raw)
    if args.total_time_limit is not None:
        from dataclasses import replace

        config = replace(config, total_time_limit_seconds=args.total_time_limit)
    campaign_dir = args.output_root / config.campaign_id
    store = OptimizationLiveStore(
        OptimizationLivePaths(
            canonical_campaign_dir=campaign_dir,
            frontend_root=args.frontend_root if args.frontend_live else None,
        )
    )
    runner = DddFleetSweepRunner(executor=_execute_trial)
    result = runner.run(
        config,
        output_root=args.output_root,
        live_store=store,
        progress=args.progress,
    )
    print(
        f"campaign={result['campaign_id']} status={result['status']} "
        f"trials={result['completed_trial_count']}/{result['trial_count']} "
        f"output={campaign_dir / 'campaign.json'}"
    )


def _execute_trial(
    *,
    config: DddFleetSweepConfig,
    policy: DddFleetPolicyConfig,
    available_fleet_count: int,
    trial_dir: Path,
    resume_checkpoint: Path | None,
    neighbor_checkpoint: Path | None,
    on_round: Any,
) -> DddFleetTrialResult:
    trial_config = DddRootCgTrialConfig(
        example_id=policy.example_id,
        available_fleet_count=available_fleet_count,
        reservoir_entry_state=policy.reservoir_entry_state,
        objective=config.objective,
        warmup_seconds=config.warmup_seconds,
        reservoir_entry_resource_ids=policy.reservoir_entry_resource_ids,
        reservoir_boundary_mode=policy.reservoir_boundary_mode,
        reservoir_dispatch_resource_ids=policy.reservoir_dispatch_resource_ids,
        reservoir_first_route_option_ids=policy.reservoir_first_route_option_ids,
        dispatch_cardinality=config.dispatch_cardinality.value,
        force_all_stop=policy.force_all_stop,
        waiting_step_seconds=policy.waiting_step_seconds,
        max_iterations=config.max_iterations,
        total_time_limit_seconds=config.total_time_limit_seconds,
        pricing_time_limit_seconds=config.pricing_time_limit_seconds,
        pricing_threads=config.pricing_threads,
        reservoir_primal_pricing_time_limit_seconds=(
            config.reservoir_primal_pricing_time_limit_seconds
        ),
        reservoir_primal_maximum_cabin_calls_per_round=(
            config.reservoir_primal_maximum_cabin_calls_per_round
        ),
    )
    outcome = DddRootCgTrialRunner().run(
        trial_config,
        output_dir=trial_dir,
        checkpoint_path=trial_dir / "checkpoint.json",
        resume_checkpoint=resume_checkpoint,
        neighbor_k_checkpoint=neighbor_checkpoint,
        progress_callback=on_round,
        console_progress=False,
    )
    payload: Mapping[str, Any] = outcome.payload
    fleet_plan = payload.get("reservoir_fleet_plan")
    dispatched = (
        None
        if not isinstance(fleet_plan, Mapping)
        else len(fleet_plan.get("dispatched_cabin_ids", ()))
    )
    return DddFleetTrialResult(
        policy_id=policy.id,
        available_fleet_count=available_fleet_count,
        status=str(payload["status"]),
        certified_lower_bound=float(payload["certified_lower_bound"]),
        validated_upper_bound=(
            None
            if payload.get("best_upper_bound") is None
            else float(payload["best_upper_bound"])
        ),
        relative_gap=(
            None
            if payload.get("relative_gap") is None
            else float(payload["relative_gap"])
        ),
        root_lp_certified=bool(payload["root_lp_certified"]),
        elapsed_seconds=float(payload["total_seconds"]),
        checkpoint_path=(
            None if outcome.checkpoint_path is None else str(outcome.checkpoint_path)
        ),
        result_path=str(outcome.output_path),
        dispatched_fleet_count=dispatched,
        detail=str(payload.get("detail", "")),
        fingerprint=outcome.fingerprint,
    )


if __name__ == "__main__":
    main()
