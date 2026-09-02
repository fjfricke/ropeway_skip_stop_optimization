from __future__ import annotations

import math

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_primal import (
    DddCpSatPrimalStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.local_resource_explainability import (
    DddCpSatLocalExplainabilityObservation,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_refinement_model import (
    DddNetworkTimeRefinementIteration,
    DddNetworkValidationResult,
    DddNetworkValidationStatus,
    DddTimeSplit,
    DddWaitingSplit,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddAnonymousFlowResult,
    DddAnonymousMasterIncumbent,
    DddAnonymousMasterProgress,
    DddNetworkTimeProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.primal_evaluation import (
    DddPrimalEvaluationStatus,
    DddPrimalEvaluationSummary,
)
from ropeway_skip_stop_optimization.optimization.ddd.support_master import (
    DddSupportConflictCut,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_refinement import (
    DddStrictTimeLiftStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (
    DddTrajectoryBoundStatus,
    DddTrajectoryOptimizerMode,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_passenger_lp import (
    DddTrajectoryPassengerLpResult,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_slot import (
    DddTrajectorySlotPoolResult,
)

def ddd_master_diagnostic_kwargs(flow: DddAnonymousFlowResult) -> dict[str, object]:
    return {
        "master_solver_status_code": flow.solver_status_code,
        "master_termination_reason": flow.termination_reason,
        "master_model_build_seconds": flow.model_build_seconds,
        "master_optimize_seconds": flow.optimize_seconds,
        "master_solution_count": flow.solution_count,
        "master_explored_node_count": flow.explored_node_count,
        "master_open_node_count": flow.open_node_count,
        "master_simplex_iteration_count": flow.simplex_iteration_count,
        "master_absolute_gap": flow.absolute_gap,
        "master_relative_gap": flow.relative_gap,
        "master_time_to_first_incumbent_seconds": (
            flow.time_to_first_incumbent_seconds
        ),
        "master_incumbent_improvements": flow.incumbent_improvements,
        "master_progress_snapshots": flow.progress_snapshots,
    }


def build_ddd_round_snapshot(
    *,
    round_index: int,
    problem: DddNetworkTimeProblem,
    node_count: int,
    arc_count: int,
    variable_count: int,
    constraint_count: int,
    prefix_variable_count: int,
    conflict_constraint_count: int,
    resource_constraint_count: int,
    mandatory_resource_constraint_count: int,
    additional_resource_constraint_count: int,
    added_resource_row_ids: tuple[str, ...],
    total_universal_resource_row_count: int,
    total_interval_resource_row_count: int,
    tracked_prefix_cabin_count: int,
    warm_start_arc_variable_count: int,
    warm_start_prefix_variable_count: int,
    warm_start_projected_cabin_count: int,
    warm_start_complete_cabin_count: int,
    path_count: int,
    master_bound: float | None,
    lower_bound: float,
    recovery_feasible: bool,
    recovery_objective: float | None,
    recovery_validation_status: DddNetworkValidationStatus,
    upper_bound: float,
    cell_lift_statuses: tuple[DddStrictTimeLiftStatus, ...],
    cell_lift_validation: DddNetworkValidationResult,
    conflict_count: int,
    added_cut_ids: tuple[str, ...],
    total_conflict_cut_count: int,
    time_splits: tuple[DddTimeSplit, ...],
    trajectory_time_split_count: int,
    resource_time_split_count: int,
    cuts: tuple[DddSupportConflictCut, ...],
    network_partition_cache_hits: int,
    network_partition_cache_misses: int,
    network_transition_cache_hits: int,
    network_transition_cache_misses: int,
    network_invalidated_state_count: int,
    network_build_seconds: float,
    master_solve_seconds: float,
    decomposition_seconds: float,
    recovery_seconds: float,
    lifting_and_validation_seconds: float,
    round_seconds: float,
    cp_sat_status: DddCpSatPrimalStatus,
    cp_sat_seconds: float,
    cp_sat_conflict_count: int,
    cp_sat_branch_count: int,
    cp_sat_candidate_count: int,
    cp_sat_search_complete: bool,
    primal_evaluation_status: DddPrimalEvaluationStatus,
    primal_evaluation_count: int,
    primal_evaluation_seconds: float,
    primal_objective_value: float | None,
    served_passenger_count: int | None,
    unserved_passenger_count: int | None,
    primal_candidate_summaries: tuple[DddPrimalEvaluationSummary, ...],
    trajectory_pool_result: DddTrajectorySlotPoolResult | None = None,
    trajectory_pool_lp_result: DddTrajectoryPassengerLpResult | None = None,
    trajectory_pricing_status: DddCpSatPrimalStatus = (DddCpSatPrimalStatus.NOT_RUN),
    trajectory_pricing_preference_count: int = 0,
    trajectory_pricing_candidate_count: int = 0,
    trajectory_pricing_objective_value: float | None = None,
    trajectory_pricing_objective_bound: float | None = None,
    trajectory_pricing_signal_fingerprint: str | None = None,
    trajectory_pricing_seconds: float = 0.0,
    trajectory_optimizer_mode: DddTrajectoryOptimizerMode = (
        DddTrajectoryOptimizerMode.OFF
    ),
    trajectory_pool_candidate_count: int = 0,
    trajectory_pool_added_option_count: int = 0,
    trajectory_pool_option_count: int = 0,
    trajectory_pool_solved_this_round: bool = False,
    cp_sat_cabin_path_status: DddCpSatPrimalStatus = (DddCpSatPrimalStatus.NOT_RUN),
    cp_sat_cabin_path_seconds: float = 0.0,
    cp_sat_cabin_path_core_cabin_ids: tuple[int, ...] = (),
    cp_sat_cabin_path_core_literal_count: int = 0,
    cp_sat_cabin_path_cut_literal_count: int = 0,
    added_cabin_path_core_cut_ids: tuple[str, ...] = (),
    aggregate_support_constraint_count: int = 0,
    aggregate_threshold_variable_count: int = 0,
    timed_flow_cover_constraint_count: int = 0,
    timed_flow_threshold_variable_count: int = 0,
    fixed_start_structural_constraint_count: int = 0,
    added_aggregate_support_cut_ids: tuple[str, ...] = (),
    cp_sat_core_literal_count: int = 0,
    cp_sat_timed_flow_core_literal_count: int = 0,
    cp_sat_timed_flow_core_resource_ids: tuple[str, ...] = (),
    cp_sat_local_explainability: DddCpSatLocalExplainabilityObservation | None = None,
    added_timed_flow_cover_cut_ids: tuple[str, ...] = (),
    cp_sat_nearest_status: DddCpSatPrimalStatus = DddCpSatPrimalStatus.NOT_RUN,
    cp_sat_nearest_seconds: float = 0.0,
    cp_sat_nearest_distance_primal: int | None = None,
    cp_sat_nearest_distance_lower_bound: float | None = None,
    added_aggregate_distance_cut_ids: tuple[str, ...] = (),
    master_passenger_variable_count: int = 0,
    master_passenger_constraint_count: int = 0,
    master_served_passenger_count: float | None = None,
    master_unserved_passenger_count: float | None = None,
    master_solver_status_code: int | None = None,
    master_termination_reason: str | None = None,
    master_model_build_seconds: float = 0.0,
    master_optimize_seconds: float = 0.0,
    master_solution_count: int = 0,
    master_explored_node_count: float = 0.0,
    master_open_node_count: float = 0.0,
    master_simplex_iteration_count: float = 0.0,
    master_absolute_gap: float | None = None,
    master_relative_gap: float | None = None,
    master_time_to_first_incumbent_seconds: float | None = None,
    master_incumbent_improvements: tuple[DddAnonymousMasterIncumbent, ...] = (),
    master_progress_snapshots: tuple[DddAnonymousMasterProgress, ...] = (),
    resource_window_resolve_count: int = 0,
    resource_window_candidate_count: int = 0,
    resource_window_violated_count: int = 0,
    resource_window_duplicate_count: int = 0,
    resource_window_added_count: int = 0,
    resource_window_entry_row_count: int = 0,
    resource_window_energy_row_count: int = 0,
    resource_window_separation_seconds: float = 0.0,
    resource_window_master_seconds: float = 0.0,
    resource_window_lower_bound_before: float | None = None,
    resource_window_lower_bound_after: float | None = None,
    waiting_splits: tuple[DddWaitingSplit, ...] = (),
) -> DddNetworkTimeRefinementIteration:
    max_visit_by_cabin: dict[int, int] = {}
    for cut in cuts:
        for literal in cut.literals:
            max_visit_by_cabin[literal.cabin_id] = max(
                max_visit_by_cabin.get(literal.cabin_id, 0),
                literal.visit_index,
            )
    positive_depths = tuple(value for value in max_visit_by_cabin.values() if value > 0)
    return DddNetworkTimeRefinementIteration(
        round_index=round_index,
        discretization_fingerprint=problem.discretization.fingerprint,
        node_count=node_count,
        arc_count=arc_count,
        variable_count=variable_count,
        constraint_count=constraint_count,
        prefix_variable_count=prefix_variable_count,
        conflict_constraint_count=conflict_constraint_count,
        tracked_prefix_cabin_count=tracked_prefix_cabin_count,
        warm_start_arc_variable_count=warm_start_arc_variable_count,
        warm_start_prefix_variable_count=warm_start_prefix_variable_count,
        warm_start_projected_cabin_count=warm_start_projected_cabin_count,
        warm_start_complete_cabin_count=warm_start_complete_cabin_count,
        decomposed_path_count=path_count,
        master_lower_bound=master_bound,
        global_lower_bound=_finite_or_none(lower_bound),
        recovery_feasible=recovery_feasible,
        recovery_objective=recovery_objective,
        recovery_validation_status=recovery_validation_status,
        global_upper_bound=_finite_or_none(upper_bound),
        cell_lift_statuses=cell_lift_statuses,
        cell_lift_validation_status=cell_lift_validation.status,
        cell_lift_validation_detail=cell_lift_validation.detail,
        conflict_count=conflict_count,
        added_cut_ids=added_cut_ids,
        total_conflict_cut_count=total_conflict_cut_count,
        time_splits=time_splits,
        time_split_count=len(time_splits),
        split_state_id=(time_splits[0].state_id if time_splits else None),
        split_boundary_seconds=(
            time_splits[0].boundary_seconds if time_splits else None
        ),
        maximum_prefix_visit_index=max(positive_depths, default=0),
        average_prefix_visit_index=(
            sum(positive_depths) / len(positive_depths) if positive_depths else 0.0
        ),
        network_partition_cache_hits=network_partition_cache_hits,
        network_partition_cache_misses=network_partition_cache_misses,
        network_transition_cache_hits=network_transition_cache_hits,
        network_transition_cache_misses=network_transition_cache_misses,
        network_invalidated_state_count=network_invalidated_state_count,
        network_build_seconds=network_build_seconds,
        master_solve_seconds=master_solve_seconds,
        decomposition_seconds=decomposition_seconds,
        recovery_seconds=recovery_seconds,
        lifting_and_validation_seconds=lifting_and_validation_seconds,
        round_seconds=round_seconds,
        resource_constraint_count=resource_constraint_count,
        mandatory_resource_constraint_count=(mandatory_resource_constraint_count),
        additional_resource_constraint_count=(additional_resource_constraint_count),
        added_resource_row_ids=added_resource_row_ids,
        total_universal_resource_row_count=(total_universal_resource_row_count),
        total_interval_resource_row_count=total_interval_resource_row_count,
        trajectory_time_split_count=trajectory_time_split_count,
        resource_time_split_count=resource_time_split_count,
        waiting_splits=waiting_splits,
        waiting_split_count=len(waiting_splits),
        waiting_interval_count=sum(
            len(partition.intervals)
            for partition in problem.waiting_discretization.partitions
        ),
        waiting_discretization_fingerprint=(
            problem.waiting_discretization.fingerprint
        ),
        cp_sat_status=cp_sat_status,
        cp_sat_seconds=cp_sat_seconds,
        cp_sat_conflict_count=cp_sat_conflict_count,
        cp_sat_branch_count=cp_sat_branch_count,
        cp_sat_candidate_count=cp_sat_candidate_count,
        cp_sat_search_complete=cp_sat_search_complete,
        cp_sat_cabin_path_status=cp_sat_cabin_path_status,
        cp_sat_cabin_path_seconds=cp_sat_cabin_path_seconds,
        cp_sat_cabin_path_core_cabin_ids=cp_sat_cabin_path_core_cabin_ids,
        cp_sat_cabin_path_core_literal_count=(cp_sat_cabin_path_core_literal_count),
        cp_sat_cabin_path_cut_literal_count=(cp_sat_cabin_path_cut_literal_count),
        added_cabin_path_core_cut_ids=added_cabin_path_core_cut_ids,
        primal_evaluation_status=primal_evaluation_status,
        primal_evaluation_count=primal_evaluation_count,
        primal_evaluation_seconds=primal_evaluation_seconds,
        primal_objective_value=primal_objective_value,
        served_passenger_count=served_passenger_count,
        unserved_passenger_count=unserved_passenger_count,
        primal_candidate_summaries=primal_candidate_summaries,
        trajectory_optimizer_mode=trajectory_optimizer_mode,
        trajectory_pool_status=(
            trajectory_pool_result.status
            if trajectory_pool_result is not None
            else None
        ),
        trajectory_bound_status=(
            trajectory_pool_result.bound_status
            if trajectory_pool_result is not None
            else (
                DddTrajectoryBoundStatus.PRIMAL_POOL_ONLY
                if trajectory_optimizer_mode
                is DddTrajectoryOptimizerMode.RESTRICTED_PRIMAL
                else None
            )
        ),
        trajectory_certified_lower_bound=(
            trajectory_pool_result.certified_lower_bound
            if trajectory_pool_result is not None
            else None
        ),
        trajectory_pool_candidate_count=trajectory_pool_candidate_count,
        trajectory_pool_added_option_count=trajectory_pool_added_option_count,
        trajectory_pool_option_count=trajectory_pool_option_count,
        trajectory_pool_solved_this_round=trajectory_pool_solved_this_round,
        trajectory_pool_option_cache_hit_count=(
            trajectory_pool_result.option_cache_hit_count
            if trajectory_pool_result is not None and trajectory_pool_solved_this_round
            else 0
        ),
        trajectory_pool_option_cache_miss_count=(
            trajectory_pool_result.option_cache_miss_count
            if trajectory_pool_result is not None and trajectory_pool_solved_this_round
            else 0
        ),
        trajectory_pool_option_cache_seconds=(
            trajectory_pool_result.option_cache_seconds
            if trajectory_pool_result is not None and trajectory_pool_solved_this_round
            else 0.0
        ),
        trajectory_pool_added_ride_variable_count=(
            trajectory_pool_result.added_ride_variable_count
            if trajectory_pool_result is not None and trajectory_pool_solved_this_round
            else 0
        ),
        trajectory_pool_master_model_created=(
            trajectory_pool_result.master_model_created
            if trajectory_pool_result is not None and trajectory_pool_solved_this_round
            else False
        ),
        trajectory_pool_master_update_seconds=(
            trajectory_pool_result.master_model_update_seconds
            if trajectory_pool_result is not None and trajectory_pool_solved_this_round
            else 0.0
        ),
        trajectory_pool_time_to_first_incumbent_seconds=(
            trajectory_pool_result.time_to_first_incumbent_seconds
            if trajectory_pool_result is not None and trajectory_pool_solved_this_round
            else None
        ),
        trajectory_pool_incumbent_improvement_count=(
            trajectory_pool_result.incumbent_improvement_count
            if trajectory_pool_result is not None and trajectory_pool_solved_this_round
            else 0
        ),
        trajectory_pool_ride_variable_count=(
            trajectory_pool_result.ride_variable_count
            if trajectory_pool_result is not None
            else 0
        ),
        trajectory_pool_conflict_round_count=(
            trajectory_pool_result.conflict_round_count
            if trajectory_pool_result is not None
            else 0
        ),
        trajectory_pool_incompatibility_count=(
            trajectory_pool_result.incompatibility_constraint_count
            if trajectory_pool_result is not None
            else 0
        ),
        trajectory_pool_seconds=(
            trajectory_pool_result.total_seconds
            if trajectory_pool_result is not None and trajectory_pool_solved_this_round
            else 0.0
        ),
        trajectory_pool_lp_status=(
            trajectory_pool_lp_result.status
            if trajectory_pool_lp_result is not None
            else None
        ),
        trajectory_pool_lp_objective_value=(
            trajectory_pool_lp_result.objective_value
            if trajectory_pool_lp_result is not None
            else None
        ),
        trajectory_pool_lp_dual_fingerprint=(
            trajectory_pool_lp_result.duals.fingerprint
            if trajectory_pool_lp_result is not None
            and trajectory_pool_lp_result.duals is not None
            else None
        ),
        trajectory_pool_lp_incompatibility_count=(
            trajectory_pool_lp_result.incompatibility_constraint_count
            if trajectory_pool_lp_result is not None
            else 0
        ),
        trajectory_pool_lp_row_separation_complete=(
            trajectory_pool_lp_result.row_separation_complete
            if trajectory_pool_lp_result is not None
            else False
        ),
        trajectory_pool_lp_build_seconds=(
            trajectory_pool_lp_result.build_seconds
            if trajectory_pool_lp_result is not None
            and trajectory_pool_solved_this_round
            else 0.0
        ),
        trajectory_pool_lp_optimize_seconds=(
            trajectory_pool_lp_result.optimize_seconds
            if trajectory_pool_lp_result is not None
            and trajectory_pool_solved_this_round
            else 0.0
        ),
        trajectory_pool_lp_total_seconds=(
            trajectory_pool_lp_result.total_seconds
            if trajectory_pool_lp_result is not None
            and trajectory_pool_solved_this_round
            else 0.0
        ),
        trajectory_pricing_status=trajectory_pricing_status,
        trajectory_pricing_preference_count=trajectory_pricing_preference_count,
        trajectory_pricing_candidate_count=trajectory_pricing_candidate_count,
        trajectory_pricing_objective_value=trajectory_pricing_objective_value,
        trajectory_pricing_objective_bound=trajectory_pricing_objective_bound,
        trajectory_pricing_signal_fingerprint=trajectory_pricing_signal_fingerprint,
        trajectory_pricing_seconds=trajectory_pricing_seconds,
        aggregate_support_constraint_count=aggregate_support_constraint_count,
        aggregate_threshold_variable_count=aggregate_threshold_variable_count,
        timed_flow_cover_constraint_count=timed_flow_cover_constraint_count,
        timed_flow_threshold_variable_count=timed_flow_threshold_variable_count,
        fixed_start_structural_constraint_count=(
            fixed_start_structural_constraint_count
        ),
        added_aggregate_support_cut_ids=added_aggregate_support_cut_ids,
        cp_sat_core_literal_count=cp_sat_core_literal_count,
        cp_sat_timed_flow_core_literal_count=(cp_sat_timed_flow_core_literal_count),
        cp_sat_timed_flow_core_resource_ids=cp_sat_timed_flow_core_resource_ids,
        cp_sat_local_explainability=cp_sat_local_explainability,
        added_timed_flow_cover_cut_ids=added_timed_flow_cover_cut_ids,
        cp_sat_nearest_status=cp_sat_nearest_status,
        cp_sat_nearest_seconds=cp_sat_nearest_seconds,
        cp_sat_nearest_distance_primal=cp_sat_nearest_distance_primal,
        cp_sat_nearest_distance_lower_bound=(cp_sat_nearest_distance_lower_bound),
        added_aggregate_distance_cut_ids=added_aggregate_distance_cut_ids,
        master_passenger_variable_count=master_passenger_variable_count,
        master_passenger_constraint_count=master_passenger_constraint_count,
        master_served_passenger_count=master_served_passenger_count,
        master_unserved_passenger_count=master_unserved_passenger_count,
        master_solver_status_code=master_solver_status_code,
        master_termination_reason=master_termination_reason,
        master_model_build_seconds=master_model_build_seconds,
        master_optimize_seconds=master_optimize_seconds,
        master_solution_count=master_solution_count,
        master_explored_node_count=master_explored_node_count,
        master_open_node_count=master_open_node_count,
        master_simplex_iteration_count=master_simplex_iteration_count,
        master_absolute_gap=master_absolute_gap,
        master_relative_gap=master_relative_gap,
        master_time_to_first_incumbent_seconds=(master_time_to_first_incumbent_seconds),
        master_incumbent_improvements=master_incumbent_improvements,
        master_progress_snapshots=master_progress_snapshots,
        resource_window_resolve_count=resource_window_resolve_count,
        resource_window_candidate_count=resource_window_candidate_count,
        resource_window_violated_count=resource_window_violated_count,
        resource_window_duplicate_count=resource_window_duplicate_count,
        resource_window_added_count=resource_window_added_count,
        resource_window_entry_row_count=resource_window_entry_row_count,
        resource_window_energy_row_count=resource_window_energy_row_count,
        resource_window_separation_seconds=resource_window_separation_seconds,
        resource_window_master_seconds=resource_window_master_seconds,
        resource_window_lower_bound_before=resource_window_lower_bound_before,
        resource_window_lower_bound_after=resource_window_lower_bound_after,
    )


def _finite_or_none(value: float) -> float | None:
    return value if math.isfinite(value) else None
