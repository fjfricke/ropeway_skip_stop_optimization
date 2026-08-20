from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import UTC, datetime
import json
import math
from pathlib import Path
from time import perf_counter
from typing import Callable

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
    DddEanPassengerPrimalEvaluator,
    DddFixedKOperatingMode,
    DddFixedKSeedCoordinator,
    DddFixedKSeedStatus,
    DddFixedKStartPolicy,
    DddFixedKTrajectoryProblem,
    DddTrajectoryConflictRowMode,
    DddTrajectoryDiversityMode,
    DddTrajectoryExactRootColumnGenerationSolver,
    DddTrajectoryMasterDualMode,
    DddTrajectoryPricingFormulation,
    DddTrajectoryRootCgIteration,
    DddTrajectoryRootCgResult,
    DddTrajectoryRootCgStatus,
    DddTrajectoryFleetMode,
    DddReservoirBoundaryConfig,
    DddReservoirBoundaryMode,
    DddReservoirPrimalPricingMode,
    DddReservoirDispatchCardinalityMode,
    DddReservoirTrajectoryStartDomain,
    DddResourceUsage,
    DddTrajectoryProblem,
    EanArtifactToDddMovementProblemAdapter,
    build_ddd_reservoir_passenger_candidates,
    build_ddd_reservoir_neighbor_k_initial_pool,
    ddd_trajectory_column,
    read_ddd_trajectory_root_cg_checkpoint,
    write_ddd_trajectory_root_cg_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    CanonicalFixedKRopeCabinStartBuilder,
    EanFleetCardinalityMode,
    EanFleetMode,
    EanPassengerCandidateBuilder,
    EanPassengerObjective,
    NetworkEanBuildArtifactBuilder,
    SparseHeadwayPairBuilder,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run exact root trajectory column generation for fixed starts, "
            "optimized initial placement, or reservoir dispatch."
        )
    )
    parser.add_argument("--example")
    parser.add_argument(
        "--fleet-mode",
        choices=(
            "example",
            "fixed_starts",
            "optimized_initial_placement",
            "reservoir_dispatch",
        ),
        default="example",
    )
    parser.add_argument("--cabins", type=int, default=3)
    parser.add_argument("--horizon", type=float, default=250.0)
    parser.add_argument(
        "--warmup-seconds",
        type=float,
        default=300.0,
        help="Passenger-free reservoir dispatch window W.",
    )
    parser.add_argument(
        "--reservoir-entry-state",
        help="Explicit movement-state id at which reservoir cabins are dispatched.",
    )
    parser.add_argument(
        "--reservoir-entry-resource",
        action="append",
        default=[],
        help="Resource id that every permitted first route must consume.",
    )
    parser.add_argument(
        "--reservoir-boundary-mode",
        choices=tuple(item.value for item in DddReservoirBoundaryMode),
        default=DddReservoirBoundaryMode.IDEAL_NON_LIMITING.value,
        help=(
            "Whether dispatch uses an ideal non-limiting interface or an explicit "
            "physical resource."
        ),
    )
    parser.add_argument(
        "--reservoir-dispatch-resource",
        action="append",
        default=[],
        help=(
            "Physical resource occupied exactly at dispatch; repeat for multiple "
            "resources. Required in physical_resource mode."
        ),
    )
    parser.add_argument(
        "--reservoir-first-route",
        action="append",
        default=[],
        help="Permitted first route-option id; repeat for multiple options.",
    )
    parser.add_argument(
        "--dispatch-cardinality",
        choices=tuple(item.value for item in DddReservoirDispatchCardinalityMode),
        default=DddReservoirDispatchCardinalityMode.OPTIONAL.value,
    )
    parser.add_argument(
        "--force-all-stop",
        action="store_true",
        help="Keep the physical skip-capable network but remove all SKIP routes.",
    )
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
    parser.add_argument(
        "--total-time-limit",
        type=float,
        default=None,
        help=(
            "Overall wall-clock budget in seconds, checked between completed "
            "rounds and including resumed checkpoint time."
        ),
    )
    parser.add_argument("--pricing-time-limit", type=float, default=5.0)
    parser.add_argument(
        "--pricing-time-limit-tier",
        action="append",
        type=float,
        default=[],
        help="Adaptive proof-pricing tier; repeat in increasing order.",
    )
    parser.add_argument("--fixed-k-certified", action="store_true")
    parser.add_argument(
        "--fixed-start-policy",
        choices=tuple(item.value for item in DddFixedKStartPolicy),
        default=DddFixedKStartPolicy.LEGACY.value,
    )
    parser.add_argument("--cp-seed-time-limit", type=float, default=30.0)
    parser.add_argument("--cp-seed-workers", type=int, default=1)
    parser.add_argument("--restricted-mip-interval", type=int, default=1)
    parser.add_argument("--restricted-mip-time-limit", type=float)
    parser.add_argument("--final-mip-time-limit", type=float, default=0.0)
    parser.add_argument("--objective-floor", type=float, default=0.0)
    parser.add_argument(
        "--waiting-step-seconds",
        type=float,
        default=1.0,
        help="Exact bounded-wait control resolution; station maxima come from the scenario.",
    )
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
        default=None,
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
    parser.add_argument(
        "--oip-primal-pricing-time-limit",
        type=float,
        default=0.0,
        help=(
            "Optional per-class OIP primal intensification budget; zero uses only "
            "incumbents retained for free from proof pricing."
        ),
    )
    parser.add_argument(
        "--reservoir-primal-pricing-time-limit",
        type=float,
        default=0.0,
        help=(
            "Per-call reservoir primal-intensification budget; zero disables "
            "the separate primal oracle."
        ),
    )
    parser.add_argument(
        "--reservoir-primal-pricing-mode",
        choices=tuple(item.value for item in DddReservoirPrimalPricingMode),
        default=DddReservoirPrimalPricingMode.COMPACT_DISPATCH_WINDOWS.value,
        help="Primal-only reservoir pricing formulation.",
    )
    parser.add_argument(
        "--reservoir-primal-max-cabin-calls",
        type=int,
        default=4,
        help="Maximum independently diversified reservoir cabins per CG round.",
    )
    parser.add_argument(
        "--reservoir-dispatch-anchor-count",
        type=int,
        default=32,
        help="Number of deterministic dispatch anchors used only for primal columns.",
    )
    parser.add_argument(
        "--reservoir-primal-max-arcs",
        type=int,
        default=25_000,
        help="Skip a primal anchor before model build when its DAG exceeds this cap.",
    )
    parser.add_argument(
        "--reservoir-primal-max-passenger-arc-product",
        type=int,
        default=250_000,
        help=(
            "Skip an anchor when time-expanded arcs times ride candidates exceed "
            "this model-build proxy."
        ),
    )
    parser.add_argument("--solver-output", action="store_true")
    parser.add_argument("--no-progress", action="store_true")
    parser.add_argument(
        "--verbose-progress",
        action="store_true",
        help="Show all diagnostic fields instead of the compact progress line.",
    )
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
        "--neighbor-k-checkpoint",
        type=Path,
        help=(
            "Start a fresh reservoir K solve from the validated incumbent in a "
            "neighboring-K checkpoint."
        ),
    )
    parser.add_argument(
        "--no-checkpoint",
        action="store_true",
        help="Disable the default atomic checkpoint written after every round.",
    )
    args = parser.parse_args()
    run_namespace(args)


def run_namespace(
    args: argparse.Namespace,
    *,
    progress_hook: Callable[[DddTrajectoryRootCgIteration], None] | None = None,
) -> dict[str, object]:
        application_started = perf_counter()
        if args.resume_checkpoint is not None and args.neighbor_k_checkpoint is not None:
            raise ValueError(
                "--resume-checkpoint and --neighbor-k-checkpoint are mutually exclusive"
            )

        if args.example is None:
            if args.fleet_mode in {
                "optimized_initial_placement",
                "reservoir_dispatch",
            }:
                raise ValueError(f"{args.fleet_mode} requires --example")
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
            fixed_start_policy = DddFixedKStartPolicy(
                getattr(args, "fixed_start_policy", DddFixedKStartPolicy.LEGACY.value)
            )
            if fixed_start_policy is DddFixedKStartPolicy.CANONICAL_ROPE:
                if args.fleet_mode != "fixed_starts":
                    raise ValueError(
                        "canonical rope starts require --fleet-mode fixed_starts"
                    )
                builder = replace(
                    builder,
                    start_builder=CanonicalFixedKRopeCabinStartBuilder(args.cabins),
                    fleet_config=replace(
                        builder.fleet_config,
                        mode=EanFleetMode.FIXED_STARTS,
                        available_fleet_count=None,
                    ),
                )
            if args.fleet_mode == "optimized_initial_placement":
                builder = replace(
                    builder,
                    fleet_config=replace(
                        builder.fleet_config,
                        mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
                        available_fleet_count=args.cabins,
                        cardinality_mode=EanFleetCardinalityMode.EXACT,
                    ),
                )
            elif (
                args.fleet_mode == "fixed_starts"
                and builder.fleet_config.mode is not EanFleetMode.FIXED_STARTS
            ):
                raise ValueError(
                    "fixed_starts requires an example with physical fixed starts"
                )
            artifact = replace(
                builder,
                headway_pair_builder=SparseHeadwayPairBuilder(),
            ).build(scenario, config)

        adapter = EanArtifactToDddMovementProblemAdapter(
            waiting_step_seconds=args.waiting_step_seconds
        )
        if args.fleet_mode == "reservoir_dispatch":
            if not args.reservoir_entry_state:
                raise ValueError(
                    "reservoir_dispatch requires the explicit --reservoir-entry-state"
                )
            core = adapter.build_movement_core(artifact)
            if args.force_all_stop:
                from ropeway_skip_stop_optimization.optimization.ddd import (
                    DddRouteDecision,
                )

                core = replace(
                    core,
                    route_options=tuple(
                        option
                        for option in core.route_options
                        if option.decision is DddRouteDecision.STOP
                    ),
                )
                core.validate()
            minimum_duration = min(
                option.duration_seconds for option in core.route_options
            )
            maximum_visit_count = (
                math.ceil(
                    (
                        args.warmup_seconds
                        + core.operational_end_seconds
                        + minimum_duration
                    )
                    / minimum_duration
                )
                + 1
            )
            trajectory_problem = DddTrajectoryProblem(
                movement_core=core,
                start_domain=DddReservoirTrajectoryStartDomain(
                    cabin_ids=tuple(range(args.cabins)),
                    boundary=DddReservoirBoundaryConfig(
                        id=f"reservoir::{args.reservoir_entry_state}",
                        entry_state_id=args.reservoir_entry_state,
                        boundary_mode=DddReservoirBoundaryMode(
                            args.reservoir_boundary_mode
                        ),
                        dispatch_resource_usages=tuple(
                            DddResourceUsage(
                                resource_id=resource_id,
                                leader_clear_offset_seconds=0.0,
                                follower_enter_offset_seconds=0.0,
                            )
                            for resource_id in sorted(
                                set(args.reservoir_dispatch_resource)
                            )
                        ),
                        required_entry_resource_ids=tuple(
                            sorted(set(args.reservoir_entry_resource))
                        ),
                        allowed_first_route_option_ids=tuple(
                            sorted(set(args.reservoir_first_route))
                        ),
                    ),
                    warmup_seconds=args.warmup_seconds,
                    maximum_visit_count=maximum_visit_count,
                    cardinality_mode=DddReservoirDispatchCardinalityMode(
                        args.dispatch_cardinality
                    ),
                ),
                waiting_policy=adapter.build_waiting_policy(artifact, core=core),
            )
            trajectory_problem.validate()
        else:
            trajectory_problem = adapter.build_trajectory_problem(artifact)
        movement = trajectory_problem.structural_movement_problem
        problem = build_initial_ddd_network_problem(movement)
        passenger_build = (
            build_ddd_reservoir_passenger_candidates(
                scenario=scenario,
                problem=trajectory_problem,
            )
            if args.fleet_mode == "reservoir_dispatch"
            else EanPassengerCandidateBuilder().build(scenario, artifact)
        )
        objective = EanPassengerObjective(args.objective)
        fixed_k_problem = None
        if getattr(args, "fixed_k_certified", False):
            fixed_k_problem = DddFixedKTrajectoryProblem(
                trajectory_problem=trajectory_problem,
                artifact=artifact,
                passenger_build=passenger_build,
                objective=objective,
                operating_mode=(
                    DddFixedKOperatingMode.ALL_STOP
                    if args.force_all_stop
                    else DddFixedKOperatingMode.SKIP_STOP
                ),
                start_policy=DddFixedKStartPolicy(
                    getattr(
                        args,
                        "fixed_start_policy",
                        DddFixedKStartPolicy.LEGACY.value,
                    )
                ),
                objective_floor=float(getattr(args, "objective_floor", 0.0)),
            )
            fixed_k_problem.validate()
            trajectory_problem = fixed_k_problem.resolved_trajectory_problem
            movement = trajectory_problem.structural_movement_problem
            problem = build_initial_ddd_network_problem(movement)
        output_stem = (
            f"{case_id}__reservoir_k{args.cabins}_w{args.warmup_seconds:g}__"
            f"{objective.value}"
            if args.fleet_mode == "reservoir_dispatch"
            else f"{case_id}__{objective.value}"
        )
        default_checkpoint_path = (
            args.output_dir / f"{output_stem}.checkpoint.json"
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
        initial_trajectories = None
        seed_result = None
        if fixed_k_problem is not None and resume_state is None:
            seed_evaluator = DddEanPassengerPrimalEvaluator(
                scenario=scenario,
                artifact=artifact,
                objective=objective,
                time_limit_seconds=getattr(args, "restricted_mip_time_limit", None),
                threads=1,
            )
            seed_result = DddFixedKSeedCoordinator(
                cp_sat_time_limit_seconds=float(
                    getattr(args, "cp_seed_time_limit", 30.0)
                ),
                cp_sat_num_workers=int(getattr(args, "cp_seed_workers", 1)),
            ).solve(
                problem,
                evaluate=lambda solution: seed_evaluator.evaluate(
                    problem, solution
                ).objective_value,
            )
            if seed_result.status is DddFixedKSeedStatus.FEASIBLE:
                initial_trajectories = seed_result.trajectories
        neighbor_source_k = None
        if args.neighbor_k_checkpoint is not None:
            if not isinstance(
                trajectory_problem.start_domain,
                DddReservoirTrajectoryStartDomain,
            ):
                raise ValueError("neighbor-K warm starts require reservoir_dispatch")
            neighbor_state = read_ddd_trajectory_root_cg_checkpoint(
                args.neighbor_k_checkpoint
            )
            source_domain = neighbor_state.reservoir_start_domain
            if source_domain is None:
                raise ValueError("neighbor-K checkpoint has no reservoir start domain")
            if neighbor_state.waiting_policy != trajectory_problem.waiting_policy:
                raise ValueError("neighbor-K checkpoint uses a different waiting policy")
            trajectories_by_id = {
                ddd_trajectory_column(
                    trajectory,
                    instance_fingerprint=neighbor_state.instance_fingerprint,
                ).id: trajectory
                for trajectory in neighbor_state.trajectories
            }
            missing = set(neighbor_state.incumbent_option_ids) - set(trajectories_by_id)
            if missing:
                raise ValueError("neighbor-K checkpoint incumbent is incomplete")
            source_incumbent = tuple(
                trajectories_by_id[option_id]
                for option_id in neighbor_state.incumbent_option_ids
            )
            initial_trajectories = build_ddd_reservoir_neighbor_k_initial_pool(
                target_problem=trajectory_problem,
                source_domain=source_domain,
                source_incumbent_trajectories=source_incumbent,
            )
            neighbor_source_k = len(source_domain.cabin_ids)
        pricing_formulation = (
            DddTrajectoryPricingFormulation(args.pricing_formulation)
            if args.pricing_formulation is not None
            else (
                DddTrajectoryPricingFormulation.TIGHT_CONVEX_HULL
                if trajectory_problem.fleet_mode
                in {
                    DddTrajectoryFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
                    DddTrajectoryFleetMode.RESERVOIR_DISPATCH,
                }
                else DddTrajectoryPricingFormulation.TIME_EXPANDED_PATH
            )
        )

        def progress(iteration: DddTrajectoryRootCgIteration) -> None:
            if progress_hook is not None:
                progress_hook(iteration)
            if args.no_progress:
                return
            if not getattr(args, "verbose_progress", False):
                print(
                    _format_compact_progress(
                        iteration,
                        mode=(
                            fixed_k_problem.operating_mode.value
                            if fixed_k_problem is not None
                            else trajectory_problem.fleet_mode.value
                        ),
                        cabin_count=len(trajectory_problem.cabin_ids),
                        max_iterations=args.max_iterations,
                    )
                )
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
            incumbent_fleet = (
                "-"
                if iteration.incumbent_dispatched_fleet_count is None
                else str(iteration.incumbent_dispatched_fleet_count)
            )
            primal_statuses = ",".join(
                f"{status}:{count}"
                for status, count in iteration.primal_pricing_status_counts
            ) or "-"
            pricing_variables = sum(
                item.model_variable_count for item in iteration.pricing_diagnostics
            )
            pricing_constraints = sum(
                item.model_linear_constraint_count
                + item.model_general_constraint_count
                for item in iteration.pricing_diagnostics
            )
            print(
                f"round={iteration.round_index:03d} "
                f"columns={iteration.trajectory_count} "
                f"starts=S{iteration.station_start_column_count}/R{iteration.rope_start_column_count} "
                f"reservoir=D{iteration.dispatched_column_count}/"
                f"S{iteration.stored_column_count}/"
                f"K{incumbent_fleet} "
                f"wait={iteration.waiting_column_count}c/"
                f"{iteration.positive_wait_visit_count}v/"
                f"{iteration.maximum_column_wait_seconds:g}s "
                f"pairs={iteration.incompatibility_pair_count} "
                f"boundary_pairs={iteration.boundary_incompatibility_pair_count} "
                f"windows={iteration.resource_window_count}"
                f"(+{iteration.added_resource_window_count}) "
                f"LB={iteration.global_lower_bound:.3f} "
                f"RMP={iteration.restricted_lp_value:.3f} "
                f"UB={upper} gap={gap} "
                f"rc={iteration.minimum_reduced_cost} rc_lb={reduced_cost_bound} "
                f"correction={correction} existing={existing_pricing_columns} "
                f"nogoods={iteration.proof_pricing_exclusion_count} "
                f"added={iteration.added_trajectory_count} "
                f"diverse={iteration.diverse_added_trajectory_count} "
                f"extra_calls={iteration.extra_pricing_call_count} "
                f"proof_solves={iteration.proof_pricing_solve_count} "
                f"reused={iteration.proof_pricing_reused_cabin_count} "
                f"primal={iteration.primal_pricing_call_count}/"
                f"{iteration.primal_pricing_candidate_count}c/"
                f"{iteration.primal_pricing_negative_candidate_count}n/"
                f"{iteration.primal_pricing_seconds:.2f}s[{primal_statuses}] "
                f"classes={iteration.bounded_start_class_count}/"
                f"{iteration.required_start_class_count}b "
                f"rel={iteration.relative_node_count}n/"
                f"{iteration.relative_arc_count}a/"
                f"{iteration.origin_product_count}p "
                f"build={iteration.pricing_model_build_seconds:.2f}s "
                f"pricing_model={pricing_variables}v/{pricing_constraints}c "
                f"exact={iteration.exact_pricing_cabin_count}/{len(trajectory_problem.cabin_ids)} "
                f"tier={iteration.pricing_tier_seconds:g}s/"
                f"retry={iteration.pricing_retry_count}/"
                f"open={iteration.unresolved_pricing_count} "
                f"mip={int(iteration.restricted_mip_ran)}/"
                f"{iteration.restricted_mip_solution_count} "
                f"remaining={('-' if iteration.remaining_budget_seconds is None else f'{iteration.remaining_budget_seconds:.1f}s')} "
                f"master={iteration.master_build_seconds + iteration.lp_seconds:.2f}s "
                f"pricing={iteration.pricing_seconds:.2f}s "
                f"separation={iteration.resource_separation_seconds:.2f}s"
            )
            for detail in iteration.primal_pricing_details:
                print(f"  primal-detail: {detail}")

        remaining_root_budget = (
            None
            if args.total_time_limit is None
            else max(1e-6, args.total_time_limit - (perf_counter() - application_started))
        )
        solver = DddTrajectoryExactRootColumnGenerationSolver(
            max_iterations=args.max_iterations,
            total_time_limit_seconds=remaining_root_budget,
            pricing_time_limit_seconds=args.pricing_time_limit,
            pricing_time_limit_tiers_seconds=tuple(
                getattr(args, "pricing_time_limit_tier", ())
            ),
            pricing_threads=args.pricing_threads,
            master_dual_mode=DddTrajectoryMasterDualMode(args.master_dual_mode),
            proof_pricing_mip_focus=args.proof_pricing_mip_focus,
            extra_pricing_mip_focus=args.extra_pricing_mip_focus,
            pricing_formulation=pricing_formulation,
            max_incompatibility_pair_checks=args.max_pair_checks,
            conflict_row_mode=DddTrajectoryConflictRowMode(args.conflict_row_mode),
            max_resource_window_rounds=args.max_resource_window_rounds,
            columns_per_cabin_per_round=args.columns_per_cabin_per_round,
            diversity_mode=DddTrajectoryDiversityMode(args.diversity_mode),
            minimum_diversity_distance=args.minimum_diversity_distance,
            extra_column_time_limit_seconds=args.extra_column_time_limit,
            oip_primal_pricing_time_limit_seconds=(args.oip_primal_pricing_time_limit),
            reservoir_primal_pricing_time_limit_seconds=(
                args.reservoir_primal_pricing_time_limit
            ),
            reservoir_primal_pricing_mode=DddReservoirPrimalPricingMode(
                args.reservoir_primal_pricing_mode
            ),
            reservoir_primal_maximum_cabin_calls_per_round=(
                args.reservoir_primal_max_cabin_calls
            ),
            reservoir_dispatch_anchor_count=args.reservoir_dispatch_anchor_count,
            reservoir_primal_maximum_arc_count=args.reservoir_primal_max_arcs,
            reservoir_primal_maximum_passenger_arc_product=(
                args.reservoir_primal_max_passenger_arc_product
            ),
            output_flag=args.solver_output,
            certified_fixed_k_mode=bool(
                getattr(args, "fixed_k_certified", False)
            ),
            objective_floor=float(getattr(args, "objective_floor", 0.0)),
            restricted_mip_interval=int(
                getattr(args, "restricted_mip_interval", 1)
            ),
            restricted_mip_time_limit_seconds=getattr(
                args, "restricted_mip_time_limit", None
            ),
            final_mip_time_limit_seconds=float(
                getattr(args, "final_mip_time_limit", 0.0)
            ),
        )
        root_solve_started = perf_counter()
        if seed_result is not None and seed_result.status is not DddFixedKSeedStatus.FEASIBLE:
            status_by_seed = {
                DddFixedKSeedStatus.MOVEMENT_INFEASIBLE: (
                    DddTrajectoryRootCgStatus.MOVEMENT_INFEASIBLE
                ),
                DddFixedKSeedStatus.UNKNOWN_NO_FEASIBLE_SEED: (
                    DddTrajectoryRootCgStatus.UNKNOWN_NO_FEASIBLE_SEED
                ),
                DddFixedKSeedStatus.INTERNAL_VALIDATION_ERROR: (
                    DddTrajectoryRootCgStatus.INTERNAL_VALIDATION_ERROR
                ),
            }
            result = DddTrajectoryRootCgResult(
                status=status_by_seed[seed_result.status],
                certified_lower_bound=float(getattr(args, "objective_floor", 0.0)),
                best_upper_bound=None,
                relative_gap=None,
                root_lp_certified=False,
                iterations=(),
                trajectories=(),
                incumbent_option_ids=(),
                incumbent_ride_values_by_id={},
                total_seconds=perf_counter() - application_started,
                detail=seed_result.detail,
                fleet_mode=trajectory_problem.fleet_mode,
                seed_kind=(
                    None if seed_result.kind is None else seed_result.kind.value
                ),
                certificate_valid=(
                    seed_result.status
                    is not DddFixedKSeedStatus.INTERNAL_VALIDATION_ERROR
                ),
                objective_floor=float(getattr(args, "objective_floor", 0.0)),
            )
        else:
            result = solver.solve(
                problem=problem,
                trajectory_problem=trajectory_problem,
                artifact=artifact,
                passenger_build=passenger_build,
                objective=objective,
                initial_trajectories=initial_trajectories,
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
            result = replace(
                result,
                total_seconds=(
                    result.total_seconds
                    + root_solve_started
                    - application_started
                ),
                seed_kind=(
                    result.seed_kind
                    if seed_result is None or seed_result.kind is None
                    else seed_result.kind.value
                ),
            )
        payload = {
            "schema_version": 3,
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "case_id": case_id,
            "scope": "exact_root_column_generation",
            "experimental": not bool(
                getattr(args, "fixed_k_certified", False)
            ),
            "fleet_mode": trajectory_problem.fleet_mode.value,
            "objective": objective.value,
            "waiting_policy": asdict(trajectory_problem.waiting_policy),
            "cabin_count": len(trajectory_problem.cabin_ids),
            "available_fleet_count": len(trajectory_problem.cabin_ids),
            "warmup_seconds": (
                args.warmup_seconds
                if args.fleet_mode == "reservoir_dispatch"
                else None
            ),
            "dispatch_cardinality": (
                args.dispatch_cardinality
                if args.fleet_mode == "reservoir_dispatch"
                else None
            ),
            "force_all_stop": bool(args.force_all_stop),
            "reservoir_start_domain": (
                asdict(trajectory_problem.start_domain)
                if isinstance(
                    trajectory_problem.start_domain,
                    DddReservoirTrajectoryStartDomain,
                )
                else None
            ),
            "horizon_seconds": artifact.config.horizon_seconds,
            "status": result.status.value,
            "certified_lower_bound": result.certified_lower_bound,
            "best_upper_bound": result.best_upper_bound,
            "relative_gap": result.relative_gap,
            "root_lp_certified": result.root_lp_certified,
            "certificate_valid": result.certificate_valid,
            "objective_floor": result.objective_floor,
            "fixed_k_certified": bool(
                getattr(args, "fixed_k_certified", False)
            ),
            "fixed_start_policy": getattr(
                args, "fixed_start_policy", DddFixedKStartPolicy.LEGACY.value
            ),
            "operating_mode": (
                None
                if fixed_k_problem is None
                else fixed_k_problem.operating_mode.value
            ),
            "fixed_k_problem_fingerprint": (
                None if fixed_k_problem is None else fixed_k_problem.fingerprint
            ),
            "seed_status": (
                None if seed_result is None else seed_result.status.value
            ),
            "seed_cp_sat_seconds": (
                None if seed_result is None else seed_result.cp_sat_seconds
            ),
            "pricing_time_limit_tiers_seconds": list(
                getattr(args, "pricing_time_limit_tier", ())
            ),
            "restricted_mip_interval": int(
                getattr(args, "restricted_mip_interval", 1)
            ),
            "restricted_mip_time_limit_seconds": getattr(
                args, "restricted_mip_time_limit", None
            ),
            "final_mip_time_limit_seconds": float(
                getattr(args, "final_mip_time_limit", 0.0)
            ),
            "conflict_row_mode": args.conflict_row_mode,
            "master_dual_mode": args.master_dual_mode,
            "proof_pricing_mip_focus": args.proof_pricing_mip_focus,
            "extra_pricing_mip_focus": args.extra_pricing_mip_focus,
            "oip_primal_pricing_time_limit_seconds": (args.oip_primal_pricing_time_limit),
            "reservoir_primal_pricing_time_limit_seconds": (
                args.reservoir_primal_pricing_time_limit
            ),
            "reservoir_primal_pricing_mode": args.reservoir_primal_pricing_mode,
            "reservoir_primal_maximum_cabin_calls_per_round": (
                args.reservoir_primal_max_cabin_calls
            ),
            "reservoir_dispatch_anchor_count": args.reservoir_dispatch_anchor_count,
            "reservoir_primal_maximum_arc_count": args.reservoir_primal_max_arcs,
            "reservoir_primal_maximum_passenger_arc_product": (
                args.reservoir_primal_max_passenger_arc_product
            ),
            "pricing_formulation": pricing_formulation.value,
            "columns_per_cabin_per_round": args.columns_per_cabin_per_round,
            "diversity_mode": args.diversity_mode,
            "trajectory_count": len(result.trajectories),
            "station_start_column_count": sum(
                item.initial_state is not None and item.initial_state.kind.value != "rope"
                for item in result.trajectories
            ),
            "rope_start_column_count": sum(
                item.initial_state is not None and item.initial_state.kind.value == "rope"
                for item in result.trajectories
            ),
            "full_start_domain_priced": result.full_start_domain_priced,
            "seed_kind": result.seed_kind,
            "neighbor_k_checkpoint": (
                None
                if args.neighbor_k_checkpoint is None
                else str(args.neighbor_k_checkpoint)
            ),
            "neighbor_source_k": neighbor_source_k,
            "fleet_plan": None if result.fleet_plan is None else asdict(result.fleet_plan),
            "reservoir_fleet_plan": (
                None
                if result.reservoir_fleet_plan is None
                else asdict(result.reservoir_fleet_plan)
            ),
            "incumbent_option_ids": result.incumbent_option_ids,
            "incumbent_ride_values_by_id": result.incumbent_ride_values_by_id,
            "checkpoint_path": (None if checkpoint_path is None else str(checkpoint_path)),
            "total_seconds": result.total_seconds,
            "total_time_limit_seconds": args.total_time_limit,
            "detail": result.detail,
            "iterations": [asdict(item) for item in result.iterations],
        }
        args.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = args.output_dir / f"{output_stem}.json"
        output_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(_format_compact_result(result, column_count=len(result.trajectories)))
        print(f"output={output_path}")
        return {
            "payload": payload,
            "output_path": output_path,
            "checkpoint_path": checkpoint_path,
            "mathematical_result": result,
        }


def _format_compact_progress(
    iteration: DddTrajectoryRootCgIteration,
    *,
    mode: str,
    cabin_count: int,
    max_iterations: int,
) -> str:
    proved_pricing_count = (
        iteration.exact_pricing_cabin_count
        + iteration.nonexact_certified_nonnegative_pricing_count
    )
    mip = (
        f"run({iteration.restricted_mip_solution_count})"
        if iteration.restricted_mip_ran
        else "-"
    )
    return (
        f"{_short_mode(mode):>3} K={cabin_count:03d} "
        f"r={iteration.round_index:03d}/{max_iterations:03d} | "
        f"LB={_format_objective(iteration.global_lower_bound)} "
        f"RMP={_format_objective(iteration.restricted_lp_value)} "
        f"UB={_format_objective(iteration.global_upper_bound)} "
        f"gap={_format_gap(iteration.global_lower_bound, iteration.global_upper_bound)} | "
        f"cols={iteration.trajectory_count:04d}(+{iteration.added_trajectory_count:02d}) "
        f"pairs={iteration.incompatibility_pair_count:05d} | "
        f"price={proved_pricing_count:02d}/{cabin_count:02d} "
        f"{iteration.pricing_seconds:5.1f}s "
        f"tier<={iteration.pricing_tier_seconds:>3g}s "
        f"open={iteration.unresolved_pricing_count:02d} | "
        f"MIP={mip:<6} left={_format_duration(iteration.remaining_budget_seconds)}"
    )


def _format_compact_result(
    result: DddTrajectoryRootCgResult,
    *,
    column_count: int,
) -> str:
    return (
        f"done status={result.status.value} | "
        f"LB={_format_objective(result.certified_lower_bound)} "
        f"UB={_format_objective(result.best_upper_bound)} "
        f"gap={_format_gap(result.certified_lower_bound, result.best_upper_bound)} | "
        f"cols={column_count:04d} time={_format_duration(result.total_seconds)}"
    )


def _short_mode(mode: str) -> str:
    return {
        "all_stop": "AS",
        "skip_stop": "SS",
        "fixed_starts": "FIX",
        "optimized_initial_placement": "OIP",
        "reservoir_dispatch": "RES",
    }.get(mode, mode[:3].upper())


def _format_objective(value: float | None) -> str:
    return f"{'-':>13}" if value is None else f"{value:13,.1f}"


def _format_gap(lower: float, upper: float | None) -> str:
    if upper is None:
        return "      -"
    absolute = max(0.0, upper - lower)
    tolerance = 1e-9 * max(1.0, abs(upper))
    relative = 0.0 if absolute <= tolerance else absolute / max(abs(upper), 1e-9)
    return f"{100.0 * relative:6.2f}%"


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "  --:--"
    rounded = max(0, round(seconds))
    hours, remainder = divmod(rounded, 3600)
    minutes, secs = divmod(remainder, 60)
    return (
        f"{hours:02d}:{minutes:02d}:{secs:02d}"
        if hours
        else f"{minutes:02d}:{secs:02d}"
    )


if __name__ == "__main__":
    main()
