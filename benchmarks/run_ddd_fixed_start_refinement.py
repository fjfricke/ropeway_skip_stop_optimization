from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import UTC, datetime
from enum import Enum
import json
import os
from pathlib import Path
from time import perf_counter

from ropeway_skip_stop_optimization.benchmarking.ddd_progress import (
    DddTerminalProgress,
    format_ddd_iteration_progress,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
    build_initial_ddd_network_problem,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowRunConfig,
    prepare_ddd_fixed_k_arc_flow_run,
)
from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddAnonymousFlowMaster,
    DddCpSatMasterCoupling,
    DddEanPassengerPrimalEvaluator,
    DddExactTimedEvent,
    DddLayeredTimeNetworkBuilder,
    DddMovementProblem,
    DddNetworkTimeProblem,
    DddNetworkTimeRefinementResult,
    DddNetworkTimeRefinementProgressStage,
    DddNetworkTimeRefinementSolver,
    DddRecoveredScheduleFlowProjector,
    DddRecoveredSchedule,
    DddPassengerMasterProblem,
    DddFixedKOperatingMode,
    DddFixedKStartPolicy,
    DddResourceWindowCutMode,
    DddTrajectoryOptimizerMode,
    EanArtifactToDddMovementProblemAdapter,
    build_ddd_cp_sat_local_explainability_report,
    build_ddd_passenger_master_problem,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanFleetMode,
    EanPassengerAssignmentDomain,
    EanPassengerObjective,
    NetworkEanBuildArtifactBuilder,
    SparseHeadwayPairBuilder,
)


DEFAULT_EXAMPLE_ID = "five_station_circle_cw_half_skip_no_wait_v0"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run conflict-driven DDD refinement on a physical fixed-start case."
        )
    )
    parser.add_argument("--example", default=DEFAULT_EXAMPLE_ID)
    parser.add_argument(
        "--cabins",
        type=int,
        help=(
            "Build a canonical exact-K instance instead of using the example's "
            "embedded fixed starts."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=tuple(item.value for item in DddFixedKOperatingMode),
        default=DddFixedKOperatingMode.SKIP_STOP.value,
    )
    parser.add_argument(
        "--start-policy",
        choices=(DddFixedKStartPolicy.CANONICAL_ROPE.value,),
        default=DddFixedKStartPolicy.CANONICAL_ROPE.value,
    )
    parser.add_argument(
        "--waiting-headway-multiplier",
        type=float,
        default=0.0,
        help=(
            "Per-station maximum waiting time as a multiple of the local "
            "exit-merge headway. Waiting remains coarsely represented until "
            "a conflict requires refinement."
        ),
    )
    parser.add_argument("--waiting-step-seconds", type=float, default=1.0)
    parser.add_argument("--max-iterations", type=int, default=100)
    parser.add_argument(
        "--time-limit",
        type=float,
        help="Shared solver wall-clock budget in seconds across all DDD phases",
    )
    parser.add_argument(
        "--primal-seed-json",
        type=Path,
        help="Previous completed runner JSON whose validated schedules seed this run",
    )
    parser.add_argument("--max-new-cuts", type=int, default=10_000)
    parser.add_argument("--max-new-time-splits", type=int, default=10_000)
    parser.add_argument(
        "--resource-window-cuts",
        choices=tuple(item.value for item in DddResourceWindowCutMode),
        default=DddResourceWindowCutMode.OFF.value,
    )
    parser.add_argument("--resource-window-max-rows", type=int, default=100)
    parser.add_argument("--resource-window-max-resolves", type=int, default=10)
    parser.add_argument("--max-prefix-variables", type=int, default=20_000)
    parser.add_argument("--max-prefix-cabins", type=int, default=8)
    parser.add_argument("--max-prefix-visit-index", type=int, default=3)
    parser.add_argument(
        "--cp-sat",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--cp-sat-time-limit", type=float, default=5.0)
    parser.add_argument("--cp-sat-workers", type=int, default=8)
    parser.add_argument("--cp-sat-retry-interval", type=int, default=10)
    parser.add_argument("--cp-sat-candidates", type=int, default=1)
    parser.add_argument("--cp-sat-min-hamming-distance", type=int, default=1)
    parser.add_argument(
        "--cp-sat-primal-bootstrap",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--cp-sat-nearest-support",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--cp-sat-nearest-support-time-limit",
        type=float,
        default=5.0,
    )
    parser.add_argument(
        "--cp-sat-timed-flow-covers",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument(
        "--cp-sat-cabin-path-cuts",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument(
        "--cp-sat-local-explainability",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument(
        "--cp-sat-local-explainability-time-limit",
        type=float,
        default=0.5,
    )
    parser.add_argument(
        "--passenger-objective",
        choices=("none", *(item.value for item in EanPassengerObjective)),
        default="none",
    )
    parser.add_argument("--passenger-time-limit", type=float, default=30.0)
    parser.add_argument("--passenger-mip-gap", type=float, default=0.0)
    parser.add_argument("--passenger-threads", type=int)
    parser.add_argument(
        "--passenger-master",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument(
        "--diagnose-fixed-schedule-passenger-relaxation",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument(
        "--passenger-master-domain",
        choices=tuple(item.value for item in EanPassengerAssignmentDomain),
        default=EanPassengerAssignmentDomain.LP_RELAXATION.value,
    )
    parser.add_argument(
        "--trajectory-slot-pool",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument(
        "--trajectory-method",
        choices=tuple(item.value for item in DddTrajectoryOptimizerMode),
        default=DddTrajectoryOptimizerMode.OFF.value,
        help=(
            "Trajectory backend; --trajectory-slot-pool remains a compatibility "
            "alias for restricted_primal"
        ),
    )
    parser.add_argument("--trajectory-slot-time-limit", type=float, default=30.0)
    parser.add_argument("--trajectory-pricing-interval", type=int, default=1)
    parser.add_argument("--trajectory-pricing-time-limit", type=float, default=5.0)
    parser.add_argument("--trajectory-pricing-candidates", type=int, default=1)
    parser.add_argument(
        "--cp-sat-diversification-interval",
        type=int,
        default=0,
        help=(
            "Re-run unrestricted CP-SAT every N DDD rounds after an incumbent "
            "exists, excluding archived route patterns; 0 disables it"
        ),
    )
    parser.add_argument(
        "--trajectory-slot-max-conflict-rounds",
        type=int,
        default=100,
    )
    parser.add_argument(
        "--progress",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--gurobi-log", action="store_true")
    parser.add_argument(
        "--reuse-network-fragments",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--projected-warm-start",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--structural-earliest-times",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmarks/output/ddd_fixed_start_refinement"),
    )
    args = parser.parse_args()
    if args.progress and args.gurobi_log:
        parser.error("--progress and --gurobi-log cannot be combined")
    if args.cabins is not None and args.cabins <= 0:
        parser.error("--cabins must be positive")
    if args.cabins is None and args.waiting_headway_multiplier:
        parser.error(
            "--waiting-headway-multiplier currently requires --cabins so the "
            "fixed-K preparation owns the waiting semantics"
        )
    trajectory_mode = DddTrajectoryOptimizerMode(args.trajectory_method)
    trajectory_enabled = (
        args.trajectory_slot_pool
        or trajectory_mode is not DddTrajectoryOptimizerMode.OFF
    )
    if trajectory_enabled and args.passenger_objective == "none":
        parser.error(
            "the trajectory optimizer requires a passenger objective; "
            "movement-feasibility runs intentionally exclude passenger heuristics"
        )
    if args.passenger_master and args.passenger_objective == "none":
        parser.error("--passenger-master requires a passenger objective")
    if args.passenger_master and not args.cp_sat:
        parser.error("--passenger-master requires CP-SAT support lifting")
    if args.cp_sat_cabin_path_cuts and not args.cp_sat:
        parser.error("--cp-sat-cabin-path-cuts requires --cp-sat")
    if args.cp_sat_local_explainability and not args.cp_sat_timed_flow_covers:
        parser.error(
            "--cp-sat-local-explainability requires --cp-sat-timed-flow-covers"
        )
    if args.diagnose_fixed_schedule_passenger_relaxation and not args.passenger_master:
        parser.error(
            "--diagnose-fixed-schedule-passenger-relaxation requires --passenger-master"
        )

    setup_started = perf_counter()
    if args.cabins is None:
        example = get_example(args.example)
        scenario = example.build_scenario()
        config = example.build_ean_config(scenario)
        builder = example.build_ean_artifact_builder(scenario, config)
        if not isinstance(builder, NetworkEanBuildArtifactBuilder):
            raise ValueError("DDD refinement requires a network EAN builder")
        if builder.fleet_config.mode is not EanFleetMode.FIXED_STARTS:
            raise ValueError("DDD refinement requires fixed cabin starts")
        artifact = replace(
            builder,
            headway_pair_builder=SparseHeadwayPairBuilder(),
        ).build(scenario, config)
        movement = EanArtifactToDddMovementProblemAdapter().build(artifact)
        problem = build_initial_ddd_network_problem(movement)
        boundary_occurrence_count = 0
    else:
        prepared = prepare_ddd_fixed_k_arc_flow_run(
            DddFixedKArcFlowRunConfig(
                example_id=args.example,
                cabin_count=args.cabins,
                operating_mode=DddFixedKOperatingMode(args.mode),
                objective=(
                    EanPassengerObjective.JOURNEY_TIME
                    if args.passenger_objective == "none"
                    else EanPassengerObjective(args.passenger_objective)
                ),
                start_policy=DddFixedKStartPolicy(args.start_policy),
                waiting_headway_multiplier=args.waiting_headway_multiplier,
                waiting_step_seconds=args.waiting_step_seconds,
            )
        )
        scenario = prepared.scenario
        artifact = prepared.problem.artifact
        trajectory_problem = prepared.problem.resolved_trajectory_problem
        movement = trajectory_problem.structural_movement_problem
        problem = build_initial_ddd_network_problem(
            movement,
            trajectory_problem.waiting_policy,
        )
        boundary_occurrence_count = len(
            prepared.problem.boundary_context.resource_occurrences
        )
        if boundary_occurrence_count:
            raise ValueError(
                "delayed-waiting refinement does not yet support a periodic "
                "balanced boundary context; use canonical_rope starts"
            )
    setup_seconds = perf_counter() - setup_started

    solver = DddNetworkTimeRefinementSolver(
        max_iterations=args.max_iterations,
        total_time_limit_seconds=args.time_limit,
        output_flag=args.gurobi_log,
        max_new_cuts_per_iteration=args.max_new_cuts,
        max_new_time_splits_per_iteration=args.max_new_time_splits,
        resource_window_cut_mode=DddResourceWindowCutMode(args.resource_window_cuts),
        max_resource_window_rows_per_resolve=args.resource_window_max_rows,
        max_resource_window_resolves_per_iteration=(args.resource_window_max_resolves),
        max_prefix_variable_count=args.max_prefix_variables,
        max_tracked_prefix_cabin_count=args.max_prefix_cabins,
        max_prefix_visit_index=args.max_prefix_visit_index,
        use_cp_sat_primal_oracle=args.cp_sat,
        cp_sat_time_limit_seconds=args.cp_sat_time_limit,
        cp_sat_num_workers=args.cp_sat_workers,
        cp_sat_retry_interval=args.cp_sat_retry_interval,
        cp_sat_max_candidate_count=args.cp_sat_candidates,
        cp_sat_minimum_hamming_distance=(args.cp_sat_min_hamming_distance),
        use_cp_sat_primal_bootstrap=args.cp_sat_primal_bootstrap,
        use_cp_sat_nearest_support=args.cp_sat_nearest_support,
        use_cp_sat_timed_flow_covers=args.cp_sat_timed_flow_covers,
        use_cp_sat_cabin_path_cuts=args.cp_sat_cabin_path_cuts,
        collect_cp_sat_local_explainability=args.cp_sat_local_explainability,
        cp_sat_local_explainability_time_limit_seconds=(
            args.cp_sat_local_explainability_time_limit
        ),
        cp_sat_nearest_support_time_limit_seconds=(
            args.cp_sat_nearest_support_time_limit
        ),
        cp_sat_master_coupling=(
            DddCpSatMasterCoupling.FIXED_AGGREGATE_SUPPORT
            if args.passenger_master
            else DddCpSatMasterCoupling.FREE_ROUTE_CHOICES
        ),
        use_trajectory_slot_pool=args.trajectory_slot_pool,
        trajectory_optimizer_mode=trajectory_mode,
        trajectory_pricing_interval=args.trajectory_pricing_interval,
        trajectory_pricing_time_limit_seconds=args.trajectory_pricing_time_limit,
        trajectory_pricing_max_candidate_count=args.trajectory_pricing_candidates,
        cp_sat_diversification_interval=args.cp_sat_diversification_interval,
        reuse_network_fragments=args.reuse_network_fragments,
        use_projected_warm_start=args.projected_warm_start,
        use_structural_earliest_times=args.structural_earliest_times,
    )
    solve_started = perf_counter()
    primal_evaluator = (
        None
        if args.passenger_objective == "none"
        else DddEanPassengerPrimalEvaluator(
            scenario=scenario,
            artifact=artifact,
            objective=EanPassengerObjective(args.passenger_objective),
            time_limit_seconds=args.passenger_time_limit,
            mip_gap=args.passenger_mip_gap,
            threads=args.passenger_threads,
            log_to_console=args.gurobi_log,
            trajectory_pool_time_limit_seconds=args.trajectory_slot_time_limit,
            trajectory_pool_max_conflict_rounds=(
                args.trajectory_slot_max_conflict_rounds
            ),
            waiting_policy=problem.waiting_policy,
        )
    )
    passenger_master_problem = (
        None
        if not args.passenger_master
        else build_ddd_passenger_master_problem(
            scenario=scenario,
            artifact=artifact,
            movement_problem=movement,
            objective=EanPassengerObjective(args.passenger_objective),
            assignment_domain=EanPassengerAssignmentDomain(
                args.passenger_master_domain
            ),
        )
    )
    initial_schedules = (
        ()
        if args.primal_seed_json is None
        else _read_primal_seed_schedules(args.primal_seed_json, movement=movement)
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_id = args.example
    if args.cabins is not None:
        wait_token = format(args.waiting_headway_multiplier, "g").replace(".", "p")
        run_id = (
            f"{args.example}__k{args.cabins}__{args.mode}__wait_{wait_token}h"
        )
    output_path = args.output_dir / f"{run_id}.json"
    completed_iterations = []

    def handle_progress(event: object) -> None:
        progress.update(event)
        stage = getattr(event, "stage", None)
        if stage is not DddNetworkTimeRefinementProgressStage.ROUND_FINISHED:
            return
        iteration = getattr(event, "iteration", None)
        if iteration is None:
            raise ValueError("finished DDD round lacks checkpoint data")
        completed_iterations.append(iteration)
        _write_atomic_json(
            output_path,
            _build_partial_payload(
                args=args,
                movement=movement,
                setup_seconds=setup_seconds,
                solve_seconds=perf_counter() - solve_started,
                iterations=completed_iterations,
            ),
        )

    with DddTerminalProgress(
        enabled=args.progress,
        max_iterations=args.max_iterations,
        description=f"DDD K={len(movement.starts)}",
    ) as progress:
        result = solver.solve(
            problem,
            progress_callback=handle_progress,
            primal_evaluator=primal_evaluator,
            passenger_master_problem=passenger_master_problem,
            initial_schedules=initial_schedules,
        )
    solve_seconds = perf_counter() - solve_started
    fixed_schedule_passenger_diagnostic = (
        _run_fixed_schedule_passenger_diagnostic(
            problem=problem,
            movement=movement,
            result=result,
            passenger_master_problem=passenger_master_problem,
            structural_earliest_times=args.structural_earliest_times,
            gurobi_log=args.gurobi_log,
        )
        if args.diagnose_fixed_schedule_passenger_relaxation
        else None
    )
    local_explainability_report = _local_explainability_report(result.iterations)

    payload = {
        "schema_version": 2,
        "complete": True,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "example_id": args.example,
        "run_id": run_id,
        "cabin_count": len(movement.starts),
        "fixed_k_requested": args.cabins,
        "operating_mode": args.mode if args.cabins is not None else None,
        "start_policy": args.start_policy if args.cabins is not None else None,
        "waiting_headway_multiplier": args.waiting_headway_multiplier,
        "waiting_step_seconds": args.waiting_step_seconds,
        "waiting_policy": asdict(problem.waiting_policy),
        "initial_waiting_discretization_fingerprint": (
            problem.waiting_discretization.fingerprint
        ),
        "boundary_occurrence_count": boundary_occurrence_count,
        "operational_end_seconds": movement.operational_end_seconds,
        "max_iterations": args.max_iterations,
        "total_time_limit_seconds": args.time_limit,
        "primal_seed_json": (
            None if args.primal_seed_json is None else str(args.primal_seed_json)
        ),
        "max_new_cuts_per_iteration": args.max_new_cuts,
        "max_new_time_splits_per_iteration": args.max_new_time_splits,
        "resource_window_cut_mode": args.resource_window_cuts,
        "resource_window_max_rows_per_resolve": args.resource_window_max_rows,
        "resource_window_max_resolves_per_iteration": (
            args.resource_window_max_resolves
        ),
        "max_prefix_variable_count": args.max_prefix_variables,
        "max_tracked_prefix_cabin_count": args.max_prefix_cabins,
        "max_prefix_visit_index": args.max_prefix_visit_index,
        "cp_sat_enabled": args.cp_sat,
        "cp_sat_time_limit_seconds": args.cp_sat_time_limit,
        "cp_sat_num_workers": args.cp_sat_workers,
        "cp_sat_retry_interval": args.cp_sat_retry_interval,
        "cp_sat_candidate_limit": args.cp_sat_candidates,
        "cp_sat_minimum_hamming_distance": (args.cp_sat_min_hamming_distance),
        "cp_sat_primal_bootstrap": args.cp_sat_primal_bootstrap,
        "cp_sat_nearest_support": args.cp_sat_nearest_support,
        "cp_sat_timed_flow_covers": args.cp_sat_timed_flow_covers,
        "cp_sat_cabin_path_cuts": args.cp_sat_cabin_path_cuts,
        "cp_sat_local_explainability": args.cp_sat_local_explainability,
        "cp_sat_local_explainability_time_limit_seconds": (
            args.cp_sat_local_explainability_time_limit
        ),
        "cp_sat_local_explainability_report": local_explainability_report,
        "cp_sat_nearest_support_time_limit_seconds": (
            args.cp_sat_nearest_support_time_limit
        ),
        "passenger_objective": args.passenger_objective,
        "passenger_master_enabled": args.passenger_master,
        "fixed_schedule_passenger_diagnostic_enabled": (
            args.diagnose_fixed_schedule_passenger_relaxation
        ),
        "fixed_schedule_passenger_diagnostic": (fixed_schedule_passenger_diagnostic),
        "passenger_master_domain": args.passenger_master_domain,
        "experiment_scope": (
            "movement_feasibility"
            if args.passenger_objective == "none"
            else (
                "anonymous_passenger_master"
                if args.passenger_master
                else "passenger_primal"
            )
        ),
        "passenger_time_limit_seconds": args.passenger_time_limit,
        "passenger_mip_gap": args.passenger_mip_gap,
        "passenger_threads": args.passenger_threads,
        "trajectory_slot_pool_enabled": trajectory_enabled,
        "trajectory_optimizer_mode": (
            DddTrajectoryOptimizerMode.RESTRICTED_PRIMAL.value
            if args.trajectory_slot_pool
            else trajectory_mode.value
        ),
        "trajectory_slot_time_limit_seconds": args.trajectory_slot_time_limit,
        "trajectory_pricing_interval": args.trajectory_pricing_interval,
        "trajectory_pricing_time_limit_seconds": args.trajectory_pricing_time_limit,
        "trajectory_pricing_max_candidate_count": args.trajectory_pricing_candidates,
        "cp_sat_diversification_interval": args.cp_sat_diversification_interval,
        "trajectory_slot_max_conflict_rounds": (
            args.trajectory_slot_max_conflict_rounds
        ),
        "reuse_network_fragments": args.reuse_network_fragments,
        "projected_warm_start": args.projected_warm_start,
        "structural_earliest_times": args.structural_earliest_times,
        "setup_seconds": setup_seconds,
        "solve_seconds": solve_seconds,
        "status": result.status.value,
        "global_lower_bound": result.global_lower_bound,
        "global_upper_bound": result.global_upper_bound,
        "absolute_gap": result.absolute_gap,
        "iteration_count": len(result.iterations),
        "conflict_cut_count": len(result.conflict_cuts),
        "aggregate_support_cut_count": len(result.aggregate_support_cuts),
        "aggregate_distance_cut_count": len(result.aggregate_distance_cuts),
        "timed_flow_cover_cut_count": len(result.timed_flow_cover_cuts),
        "cp_sat_bootstrap_status": result.cp_sat_bootstrap_status.value,
        "cp_sat_bootstrap_seconds": result.cp_sat_bootstrap_seconds,
        "cp_sat_bootstrap_candidate_count": (result.cp_sat_bootstrap_candidate_count),
        "cp_sat_bootstrap_objective": result.cp_sat_bootstrap_objective,
        "final_discretization_fingerprint": (result.final_discretization.fingerprint),
        "final_waiting_discretization_fingerprint": (
            result.final_waiting_discretization.fingerprint
        ),
        "schedule_count": len(result.schedules),
        "schedules": [asdict(schedule) for schedule in result.schedules],
        "primal_evaluation": (
            asdict(result.primal_evaluation)
            if result.primal_evaluation is not None
            else None
        ),
        "iterations": [asdict(iteration) for iteration in result.iterations],
    }
    _write_atomic_json(output_path, payload)

    print(
        " ".join(
            (
                f"status={result.status.value}",
                f"rounds={len(result.iterations)}",
                f"LB={result.global_lower_bound}",
                f"UB={result.global_upper_bound}",
                (
                    f"passenger={result.primal_evaluation.objective_value}"
                    if result.primal_evaluation is not None
                    else "passenger=-"
                ),
                f"cuts={len(result.conflict_cuts)}",
                f"setup={setup_seconds:.2f}s",
                f"solve={solve_seconds:.2f}s",
                f"output={output_path}",
            )
        )
    )
    if result.iterations:
        print(format_ddd_iteration_progress(result.iterations[-1]))
    if fixed_schedule_passenger_diagnostic is not None:
        underestimate = fixed_schedule_passenger_diagnostic["absolute_underestimate"]
        relative = fixed_schedule_passenger_diagnostic["relative_underestimate"]
        print(
            "fixed_schedule_passenger "
            f"relaxed={fixed_schedule_passenger_diagnostic['relaxed_objective']} "
            f"reference={fixed_schedule_passenger_diagnostic['reference_objective']} "
            f"reference_status={fixed_schedule_passenger_diagnostic['reference_solver_status']} "
            f"underestimate={underestimate} relative={relative}"
        )
    if local_explainability_report is not None:
        print(
            "local_explainability "
            f"observations={local_explainability_report['observation_count']} "
            f"single={local_explainability_report['single_resource_count']} "
            f"group={local_explainability_report['resource_group_count']} "
            f"global={local_explainability_report['global_count']} "
            f"unresolved={local_explainability_report['unresolved_count']} "
            f"resource_touching="
            f"{local_explainability_report['resource_touching_core_count']} "
            f"probe={local_explainability_report['total_probe_seconds']:.2f}s"
        )


def _run_fixed_schedule_passenger_diagnostic(
    *,
    problem: DddNetworkTimeProblem,
    movement: DddMovementProblem,
    result: DddNetworkTimeRefinementResult,
    passenger_master_problem: DddPassengerMasterProblem | None,
    structural_earliest_times: bool,
    gurobi_log: bool,
) -> dict[str, object]:
    schedules = result.schedules
    exact_evaluation = result.primal_evaluation
    if not schedules or exact_evaluation is None:
        return {
            "status": "not_available",
            "reason": "no physically feasible evaluated schedule is available",
        }
    reference_objective = exact_evaluation.objective_value
    if reference_objective is None:
        return {
            "status": "not_available",
            "reason": "the exact passenger recourse has no objective value",
        }
    if passenger_master_problem is None:
        raise ValueError("fixed-schedule diagnostic needs a passenger master")

    started = perf_counter()
    projector = DddRecoveredScheduleFlowProjector()
    diagnostic_problem = projector.refine_discretization(
        problem.with_discretization(result.final_discretization),
        schedules,
    )
    builder = DddLayeredTimeNetworkBuilder(
        use_structural_earliest_times=structural_earliest_times
    )
    network = builder.build(diagnostic_problem)
    fixing = projector.project(diagnostic_problem, network, schedules)
    fixed_result = DddAnonymousFlowMaster(output_flag=gurobi_log).solve(
        network,
        fixed_flow=fixing,
        passenger_problem=passenger_master_problem,
        fixed_start_movement_problem=movement,
    )
    relaxed_objective = fixed_result.objective_value
    if relaxed_objective is None or fixed_result.passenger_solution is None:
        raise RuntimeError("fixed-schedule passenger diagnostic has no solution")
    reference_is_optimal = exact_evaluation.solver_status == "OPTIMAL"
    difference_to_reference = reference_objective - relaxed_objective
    if reference_is_optimal and difference_to_reference < -1e-5:
        raise RuntimeError("fixed-schedule passenger relaxation exceeds exact recourse")
    absolute_underestimate = (
        max(0.0, difference_to_reference) if reference_is_optimal else None
    )
    scale = abs(reference_objective)
    relative_underestimate = (
        absolute_underestimate / scale
        if absolute_underestimate is not None and scale > 1e-9
        else None
    )
    return {
        "status": (
            "optimal_reference"
            if reference_is_optimal
            else "feasible_reference_not_optimal"
        ),
        "relaxed_objective": relaxed_objective,
        "reference_objective": reference_objective,
        "reference_solver_status": exact_evaluation.solver_status,
        "reference_is_optimal": reference_is_optimal,
        "difference_to_reference": difference_to_reference,
        "absolute_underestimate": absolute_underestimate,
        "relative_underestimate": relative_underestimate,
        "network_node_count": len(network.nodes),
        "network_arc_count": len(network.arcs),
        "fixed_flow_constraint_count": fixed_result.fixed_flow_constraint_count,
        "model_variable_count": fixed_result.variable_count,
        "model_constraint_count": fixed_result.constraint_count,
        "served_passenger_count": (
            fixed_result.passenger_solution.served_passenger_count
        ),
        "unserved_passenger_count": (
            fixed_result.passenger_solution.unserved_passenger_count
        ),
        "build_seconds": fixed_result.model_build_seconds,
        "solve_seconds": fixed_result.optimize_seconds,
        "total_seconds": perf_counter() - started,
        "exact_time_cell_count": sum(
            1
            for partition in diagnostic_problem.discretization.partitions
            for lower, upper in zip(
                partition.boundaries_ticks[:-1],
                partition.boundaries_ticks[1:],
                strict=True,
            )
            if upper == lower + 1
        ),
    }


def _json_default(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _read_primal_seed_schedules(
    path: Path,
    *,
    movement: DddMovementProblem,
) -> tuple[DddRecoveredSchedule, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_schedules = payload.get("schedules")
    if isinstance(raw_schedules, list) and raw_schedules:
        schedules = tuple(
            DddRecoveredSchedule(
                cabin_id=int(item["cabin_id"]),
                route_option_ids=tuple(
                    str(value) for value in item["route_option_ids"]
                ),
                events=tuple(
                    DddExactTimedEvent(
                        event_index=int(event["event_index"]),
                        state_id=str(event["state_id"]),
                        time_seconds=float(event["time_seconds"]),
                    )
                    for event in item["events"]
                ),
                objective_value=float(item["objective_value"]),
            )
            for item in raw_schedules
        )
    else:
        schedules = _schedules_from_exact_trajectory_supports(payload, movement)
    if tuple(schedule.cabin_id for schedule in schedules) != tuple(
        sorted(schedule.cabin_id for schedule in schedules)
    ):
        raise ValueError("DDD primal-seed schedules are not cabin-sorted")
    return schedules


def _schedules_from_exact_trajectory_supports(
    payload: dict[str, object],
    movement: DddMovementProblem,
) -> tuple[DddRecoveredSchedule, ...]:
    raw_supports = payload.get("trajectory_supports")
    if not isinstance(raw_supports, list) or not raw_supports:
        raise ValueError("DDD primal-seed JSON contains no serialized schedules")
    starts_by_cabin = {start.cabin_id: start for start in movement.starts}
    options_by_id = {option.id: option for option in movement.route_options}
    schedules: list[DddRecoveredSchedule] = []
    for raw in raw_supports:
        cabin_id = int(raw["cabin_id"])
        route_option_ids = tuple(str(value) for value in raw["route_option_ids"])
        switch_times = tuple(float(value) for value in raw["switch_times_seconds"])
        waits = tuple(float(value) for value in raw["wait_seconds"])
        if not route_option_ids or not (
            len(route_option_ids) == len(switch_times) == len(waits)
        ):
            raise ValueError("exact trajectory support dimensions are inconsistent")
        states = [starts_by_cabin[cabin_id].state_id]
        states.extend(options_by_id[option_id].to_state_id for option_id in route_option_ids)
        terminal_time = (
            switch_times[-1]
            + options_by_id[route_option_ids[-1]].duration_seconds
            + waits[-1]
        )
        event_times = (*switch_times, terminal_time)
        schedules.append(
            DddRecoveredSchedule(
                cabin_id=cabin_id,
                route_option_ids=route_option_ids,
                events=tuple(
                    DddExactTimedEvent(index, state_id, time_seconds)
                    for index, (state_id, time_seconds) in enumerate(
                        zip(states, event_times, strict=True)
                    )
                ),
                objective_value=0.0,
            )
        )
    return tuple(sorted(schedules, key=lambda item: item.cabin_id))


def _local_explainability_report(
    iterations: tuple[object, ...] | list[object],
) -> dict[str, object] | None:
    observations = tuple(
        observation
        for iteration in iterations
        if (observation := getattr(iteration, "cp_sat_local_explainability", None))
        is not None
    )
    if not observations:
        return None
    return asdict(build_ddd_cp_sat_local_explainability_report(observations))


def _build_partial_payload(
    *,
    args: argparse.Namespace,
    movement: object,
    setup_seconds: float,
    solve_seconds: float,
    iterations: list[object],
) -> dict[str, object]:
    last = iterations[-1]
    return {
        "schema_version": 2,
        "complete": False,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "example_id": args.example,
        "cabin_count": len(getattr(movement, "starts")),
        "operational_end_seconds": getattr(movement, "operational_end_seconds"),
        "max_iterations": args.max_iterations,
        "total_time_limit_seconds": args.time_limit,
        "passenger_objective": args.passenger_objective,
        "passenger_master_enabled": args.passenger_master,
        "fixed_schedule_passenger_diagnostic_enabled": (
            args.diagnose_fixed_schedule_passenger_relaxation
        ),
        "passenger_master_domain": args.passenger_master_domain,
        "cp_sat_enabled": args.cp_sat,
        "cp_sat_time_limit_seconds": args.cp_sat_time_limit,
        "cp_sat_primal_bootstrap": args.cp_sat_primal_bootstrap,
        "cp_sat_nearest_support": args.cp_sat_nearest_support,
        "cp_sat_timed_flow_covers": args.cp_sat_timed_flow_covers,
        "cp_sat_cabin_path_cuts": args.cp_sat_cabin_path_cuts,
        "cp_sat_local_explainability": args.cp_sat_local_explainability,
        "cp_sat_local_explainability_time_limit_seconds": (
            args.cp_sat_local_explainability_time_limit
        ),
        "cp_sat_local_explainability_report": (
            _local_explainability_report(iterations)
        ),
        "cp_sat_nearest_support_time_limit_seconds": (
            args.cp_sat_nearest_support_time_limit
        ),
        "cp_sat_diversification_interval": args.cp_sat_diversification_interval,
        "structural_earliest_times": args.structural_earliest_times,
        "setup_seconds": setup_seconds,
        "solve_seconds": solve_seconds,
        "status": "running",
        "global_lower_bound": getattr(last, "global_lower_bound"),
        "global_upper_bound": getattr(last, "global_upper_bound"),
        "iteration_count": len(iterations),
        "last_completed_round": getattr(last, "round_index"),
        "conflict_cut_ids": [
            cut_id
            for iteration in iterations
            for cut_id in getattr(iteration, "added_cut_ids")
        ],
        "aggregate_support_cut_ids": [
            cut_id
            for iteration in iterations
            for cut_id in getattr(iteration, "added_aggregate_support_cut_ids")
        ],
        "aggregate_distance_cut_ids": [
            cut_id
            for iteration in iterations
            for cut_id in getattr(iteration, "added_aggregate_distance_cut_ids")
        ],
        "timed_flow_cover_cut_ids": [
            cut_id
            for iteration in iterations
            for cut_id in getattr(iteration, "added_timed_flow_cover_cut_ids")
        ],
        "final_discretization_fingerprint": getattr(last, "discretization_fingerprint"),
        "iterations": [asdict(iteration) for iteration in iterations],
    }


def _write_atomic_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    serialized = (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
        + "\n"
    )
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(serialized)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


if __name__ == "__main__":
    main()
