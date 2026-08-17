from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import UTC, datetime
import json
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.ddd_cases import (
    THREE_STATION_EXHAUSTIVE_BOUND_CASE_ID,
    build_three_station_exhaustive_bound_artifact,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
    build_initial_ddd_network_problem,
)
from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.examples.three_station import (
    build_three_station_scenario,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddTrajectoryConflictRowMode,
    DddTrajectoryDiversityMode,
    DddTrajectoryExactRootColumnGenerationSolver,
    DddTrajectoryMasterDualMode,
    DddTrajectoryPricingFormulation,
    DddTrajectoryRootCgIteration,
    EanArtifactToDddMovementProblemAdapter,
    read_ddd_trajectory_root_cg_checkpoint,
    write_ddd_trajectory_root_cg_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanPassengerCandidateBuilder,
    EanPassengerObjective,
    NetworkEanBuildArtifactBuilder,
    SparseHeadwayPairBuilder,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run exact no-wait root trajectory column generation."
    )
    parser.add_argument("--example")
    parser.add_argument("--cabins", type=int, default=3)
    parser.add_argument("--horizon", type=float, default=250.0)
    parser.add_argument(
        "--objective",
        choices=tuple(item.value for item in EanPassengerObjective),
        default=EanPassengerObjective.JOURNEY_TIME.value,
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=30,
        help="Total round limit, including rounds loaded from a checkpoint.",
    )
    parser.add_argument("--pricing-time-limit", type=float, default=5.0)
    parser.add_argument("--pricing-threads", type=int, default=1)
    parser.add_argument(
        "--master-dual-mode",
        choices=tuple(item.value for item in DddTrajectoryMasterDualMode),
        default=DddTrajectoryMasterDualMode.DEFAULT.value,
    )
    parser.add_argument("--proof-pricing-mip-focus", type=int, default=2)
    parser.add_argument("--extra-pricing-mip-focus", type=int, default=1)
    parser.add_argument(
        "--pricing-formulation",
        choices=tuple(item.value for item in DddTrajectoryPricingFormulation),
        default=DddTrajectoryPricingFormulation.TIME_EXPANDED_PATH.value,
    )
    parser.add_argument("--max-pair-checks", type=int, default=2_000_000)
    parser.add_argument(
        "--conflict-row-mode",
        choices=tuple(item.value for item in DddTrajectoryConflictRowMode),
        default=DddTrajectoryConflictRowMode.PAIR_ONLY.value,
    )
    parser.add_argument("--max-resource-window-rounds", type=int, default=100)
    parser.add_argument("--columns-per-cabin-per-round", type=int, default=1)
    parser.add_argument(
        "--diversity-mode",
        choices=tuple(item.value for item in DddTrajectoryDiversityMode),
        default=DddTrajectoryDiversityMode.OFF.value,
    )
    parser.add_argument("--minimum-diversity-distance", type=int, default=1)
    parser.add_argument("--extra-column-time-limit", type=float, default=10.0)
    parser.add_argument("--solver-output", action="store_true")
    parser.add_argument("--no-progress", action="store_true")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmarks/output/ddd_trajectory_root_cg"),
    )
    parser.add_argument(
        "--checkpoint-path",
        type=Path,
        help="Checkpoint destination; defaults to a case-specific file in output-dir.",
    )
    parser.add_argument(
        "--resume-checkpoint",
        type=Path,
        help="Resume a completed-round checkpoint and continue up to max-iterations.",
    )
    parser.add_argument(
        "--no-checkpoint",
        action="store_true",
        help="Disable the default atomic checkpoint written after every round.",
    )
    args = parser.parse_args()

    if args.example is None:
        case_id = THREE_STATION_EXHAUSTIVE_BOUND_CASE_ID
        artifact = build_three_station_exhaustive_bound_artifact(
            cabin_count=args.cabins,
            horizon_seconds=args.horizon,
        )
        scenario = replace(build_three_station_scenario(), id=artifact.scenario_id)
    else:
        case_id = args.example
        example = get_example(args.example)
        scenario = example.build_scenario()
        config = example.build_ean_config(scenario)
        builder = example.build_ean_artifact_builder(scenario, config)
        if not isinstance(builder, NetworkEanBuildArtifactBuilder):
            raise ValueError("trajectory root CG requires the network EAN builder")
        artifact = replace(
            builder,
            headway_pair_builder=SparseHeadwayPairBuilder(),
        ).build(scenario, config)

    movement = EanArtifactToDddMovementProblemAdapter().build(artifact)
    problem = build_initial_ddd_network_problem(movement)
    passenger_build = EanPassengerCandidateBuilder().build(scenario, artifact)
    objective = EanPassengerObjective(args.objective)
    default_checkpoint_path = (
        args.output_dir / f"{case_id}__{objective.value}.checkpoint.json"
    )
    checkpoint_path = (
        None
        if args.no_checkpoint
        else args.checkpoint_path or args.resume_checkpoint or default_checkpoint_path
    )
    resume_state = (
        read_ddd_trajectory_root_cg_checkpoint(args.resume_checkpoint)
        if args.resume_checkpoint is not None
        else None
    )

    def progress(iteration: DddTrajectoryRootCgIteration) -> None:
        if args.no_progress:
            return
        upper = (
            "-"
            if iteration.global_upper_bound is None
            else f"{iteration.global_upper_bound:.3f}"
        )
        gap = (
            "-"
            if iteration.global_upper_bound is None
            else f"{100.0 * max(0.0, iteration.global_upper_bound - iteration.global_lower_bound) / max(abs(iteration.global_upper_bound), 1e-9):.3f}%"
        )
        reduced_cost_bound = (
            "-"
            if iteration.minimum_certified_reduced_cost_bound is None
            else f"{iteration.minimum_certified_reduced_cost_bound:.3f}"
        )
        correction = (
            "-"
            if iteration.pricing_bound_correction is None
            else f"{iteration.pricing_bound_correction:.3f}"
        )
        existing_pricing_columns = sum(
            item.option_is_existing for item in iteration.pricing_diagnostics
        )
        print(
            f"round={iteration.round_index:03d} "
            f"columns={iteration.trajectory_count} "
            f"pairs={iteration.incompatibility_pair_count} "
            f"windows={iteration.resource_window_count}"
            f"(+{iteration.added_resource_window_count}) "
            f"LB={iteration.global_lower_bound:.3f} UB={upper} gap={gap} "
            f"rc={iteration.minimum_reduced_cost} rc_lb={reduced_cost_bound} "
            f"correction={correction} existing={existing_pricing_columns} "
            f"nogoods={iteration.proof_pricing_exclusion_count} "
            f"added={iteration.added_trajectory_count} "
            f"diverse={iteration.diverse_added_trajectory_count} "
            f"extra_calls={iteration.extra_pricing_call_count} "
            f"exact={iteration.exact_pricing_cabin_count}/{len(movement.starts)} "
            f"master={iteration.master_build_seconds + iteration.lp_seconds:.2f}s "
            f"pricing={iteration.pricing_seconds:.2f}s "
            f"separation={iteration.resource_separation_seconds:.2f}s"
        )

    result = DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=args.max_iterations,
        pricing_time_limit_seconds=args.pricing_time_limit,
        pricing_threads=args.pricing_threads,
        master_dual_mode=DddTrajectoryMasterDualMode(args.master_dual_mode),
        proof_pricing_mip_focus=args.proof_pricing_mip_focus,
        extra_pricing_mip_focus=args.extra_pricing_mip_focus,
        pricing_formulation=DddTrajectoryPricingFormulation(args.pricing_formulation),
        max_incompatibility_pair_checks=args.max_pair_checks,
        conflict_row_mode=DddTrajectoryConflictRowMode(args.conflict_row_mode),
        max_resource_window_rounds=args.max_resource_window_rounds,
        columns_per_cabin_per_round=args.columns_per_cabin_per_round,
        diversity_mode=DddTrajectoryDiversityMode(args.diversity_mode),
        minimum_diversity_distance=args.minimum_diversity_distance,
        extra_column_time_limit_seconds=args.extra_column_time_limit,
        output_flag=args.solver_output,
    ).solve(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=objective,
        resume_state=resume_state,
        progress_callback=progress,
        checkpoint_callback=(
            None
            if checkpoint_path is None
            else lambda state: write_ddd_trajectory_root_cg_checkpoint(
                checkpoint_path,
                state,
            )
        ),
    )
    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "case_id": case_id,
        "scope": "fixed_starts_no_wait_exact_root_column_generation",
        "objective": objective.value,
        "cabin_count": len(movement.starts),
        "horizon_seconds": artifact.config.horizon_seconds,
        "status": result.status.value,
        "certified_lower_bound": result.certified_lower_bound,
        "best_upper_bound": result.best_upper_bound,
        "relative_gap": result.relative_gap,
        "root_lp_certified": result.root_lp_certified,
        "conflict_row_mode": args.conflict_row_mode,
        "master_dual_mode": args.master_dual_mode,
        "proof_pricing_mip_focus": args.proof_pricing_mip_focus,
        "extra_pricing_mip_focus": args.extra_pricing_mip_focus,
        "pricing_formulation": args.pricing_formulation,
        "columns_per_cabin_per_round": args.columns_per_cabin_per_round,
        "diversity_mode": args.diversity_mode,
        "trajectory_count": len(result.trajectories),
        "incumbent_option_ids": result.incumbent_option_ids,
        "incumbent_ride_values_by_id": result.incumbent_ride_values_by_id,
        "checkpoint_path": (None if checkpoint_path is None else str(checkpoint_path)),
        "total_seconds": result.total_seconds,
        "detail": result.detail,
        "iterations": [asdict(item) for item in result.iterations],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / f"{case_id}__{objective.value}.json"
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"status={result.status.value} LB={result.certified_lower_bound} "
        f"UB={result.best_upper_bound} gap={result.relative_gap} "
        f"columns={len(result.trajectories)} time={result.total_seconds:.2f}s "
        f"output={output_path}"
    )


if __name__ == "__main__":
    main()
