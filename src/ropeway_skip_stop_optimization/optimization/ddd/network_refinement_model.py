from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from ropeway_skip_stop_optimization.optimization.ddd.aggregate_support import (
    DddAggregateSupportCut,
    DddAggregateSupportDistanceCut,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_primal import (
    DddCpSatPrimalStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.local_resource_explainability import (
    DddCpSatLocalExplainabilityObservation,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddAnonymousMasterIncumbent,
    DddAnonymousMasterProgress,
)
from ropeway_skip_stop_optimization.optimization.ddd.primal_evaluation import (
    DddPrimalEvaluationResult,
    DddPrimalEvaluationStatus,
    DddPrimalEvaluationSummary,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceConflict,
    DddReferenceSolution,
)
from ropeway_skip_stop_optimization.optimization.ddd.support_master import (
    DddSupportConflictCut,
    DddSupportSelection,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_refinement import (
    DddRecoveredSchedule,
    DddStrictTimeLiftStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_space import (
    DddTimeDiscretization,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_quantize_time_seconds,
)
from ropeway_skip_stop_optimization.optimization.ddd.timed_flow_cover import (
    DddTimedFlowCoverCut,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (
    DddTrajectoryBoundStatus,
    DddTrajectoryOptimizerMode,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_passenger_lp import (
    DddTrajectoryPassengerLpStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_slot import (
    DddTrajectorySlotPoolStatus,
)


class DddNetworkTimeRefinementStatus(StrEnum):
    OPTIMAL = "optimal"
    FEASIBLE_WITH_GAP = "feasible_with_gap"
    UNKNOWN_NO_INCUMBENT = "unknown_no_incumbent"
    RELAXATION_INFEASIBLE = "relaxation_infeasible"
    EXACT_INFEASIBLE = "exact_infeasible"
    REFINEMENT_STALLED = "refinement_stalled"
    REFINEMENT_BUDGET_EXHAUSTED = "refinement_budget_exhausted"
    INVALID_INTERNAL = "invalid_internal"


class DddNetworkValidationStatus(StrEnum):
    """Outcome of validation against the complete physical movement problem."""

    NOT_RUN = "not_run"
    FEASIBLE = "feasible"
    HORIZON_INCOMPLETE = "horizon_incomplete"
    RESOURCE_CONFLICT = "resource_conflict"
    INVALID = "invalid"


@dataclass(frozen=True, order=True)
class DddTimeSplit:
    state_id: str
    boundary_seconds: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "boundary_seconds",
            ddd_quantize_time_seconds(self.boundary_seconds),
        )


class DddNetworkTimeRefinementProgressStage(StrEnum):
    PRIMAL_BOOTSTRAP_STARTED = "primal_bootstrap_started"
    PRIMAL_BOOTSTRAP_FINISHED = "primal_bootstrap_finished"
    ROUND_STARTED = "round_started"
    NETWORK_BUILT = "network_built"
    MASTER_STARTED = "master_started"
    MASTER_PROGRESS = "master_progress"
    MASTER_FINISHED = "master_finished"
    RESOURCE_WINDOW_SEPARATION_FINISHED = "resource_window_separation_finished"
    DECOMPOSITION_FINISHED = "decomposition_finished"
    PRIMAL_ORACLE_CANDIDATE_FOUND = "primal_oracle_candidate_found"
    PRIMAL_ORACLE_FINISHED = "primal_oracle_finished"
    PRIMAL_EVALUATION_FINISHED = "primal_evaluation_finished"
    RECOVERY_FINISHED = "recovery_finished"
    LIFTING_FINISHED = "lifting_finished"
    TRAJECTORY_POOL_STARTED = "trajectory_pool_started"
    TRAJECTORY_POOL_FINISHED = "trajectory_pool_finished"
    ROUND_FINISHED = "round_finished"


@dataclass(frozen=True)
class DddNetworkTimeRefinementProgressEvent:
    stage: DddNetworkTimeRefinementProgressStage
    round_index: int
    max_iterations: int
    total_elapsed_seconds: float
    iteration: DddNetworkTimeRefinementIteration | None = None
    candidate_index: int | None = None
    candidate_limit: int | None = None
    candidate_elapsed_seconds: float | None = None
    primal_best_objective: float | None = None
    master_progress: DddAnonymousMasterProgress | None = None
    global_lower_bound: float | None = None
    global_upper_bound: float | None = None


DddNetworkTimeRefinementProgressCallback = Callable[
    [DddNetworkTimeRefinementProgressEvent], None
]


@dataclass(frozen=True)
class DddNetworkValidationResult:
    status: DddNetworkValidationStatus
    solution: DddReferenceSolution | None
    detail: str | None
    conflicts: tuple[DddReferenceConflict, ...]
    cuts: tuple[DddSupportConflictCut, ...]
    support_selection: DddSupportSelection | None = None

    @classmethod
    def not_run(cls) -> DddNetworkValidationResult:
        return cls(
            status=DddNetworkValidationStatus.NOT_RUN,
            solution=None,
            detail=None,
            conflicts=(),
            cuts=(),
        )


@dataclass(frozen=True)
class DddNetworkTimeRefinementIteration:
    round_index: int
    discretization_fingerprint: str
    node_count: int
    arc_count: int
    variable_count: int
    constraint_count: int
    prefix_variable_count: int
    conflict_constraint_count: int
    tracked_prefix_cabin_count: int
    warm_start_arc_variable_count: int
    warm_start_prefix_variable_count: int
    warm_start_projected_cabin_count: int
    warm_start_complete_cabin_count: int
    decomposed_path_count: int
    master_lower_bound: float | None
    global_lower_bound: float | None
    recovery_feasible: bool
    recovery_objective: float | None
    recovery_validation_status: DddNetworkValidationStatus
    global_upper_bound: float | None
    cell_lift_statuses: tuple[DddStrictTimeLiftStatus, ...]
    cell_lift_validation_status: DddNetworkValidationStatus
    cell_lift_validation_detail: str | None
    conflict_count: int
    added_cut_ids: tuple[str, ...]
    total_conflict_cut_count: int
    time_splits: tuple[DddTimeSplit, ...]
    time_split_count: int
    split_state_id: str | None
    split_boundary_seconds: float | None
    maximum_prefix_visit_index: int
    average_prefix_visit_index: float
    network_partition_cache_hits: int
    network_partition_cache_misses: int
    network_transition_cache_hits: int
    network_transition_cache_misses: int
    network_invalidated_state_count: int
    network_build_seconds: float
    master_solve_seconds: float
    decomposition_seconds: float
    recovery_seconds: float
    lifting_and_validation_seconds: float
    round_seconds: float
    resource_constraint_count: int = 0
    mandatory_resource_constraint_count: int = 0
    additional_resource_constraint_count: int = 0
    added_resource_row_ids: tuple[str, ...] = ()
    total_universal_resource_row_count: int = 0
    total_interval_resource_row_count: int = 0
    trajectory_time_split_count: int = 0
    resource_time_split_count: int = 0
    cp_sat_status: DddCpSatPrimalStatus = DddCpSatPrimalStatus.NOT_RUN
    cp_sat_seconds: float = 0.0
    cp_sat_conflict_count: int = 0
    cp_sat_branch_count: int = 0
    cp_sat_candidate_count: int = 0
    cp_sat_search_complete: bool = False
    cp_sat_cabin_path_status: DddCpSatPrimalStatus = DddCpSatPrimalStatus.NOT_RUN
    cp_sat_cabin_path_seconds: float = 0.0
    cp_sat_cabin_path_core_cabin_ids: tuple[int, ...] = ()
    cp_sat_cabin_path_core_literal_count: int = 0
    cp_sat_cabin_path_cut_literal_count: int = 0
    added_cabin_path_core_cut_ids: tuple[str, ...] = ()
    primal_evaluation_status: DddPrimalEvaluationStatus = (
        DddPrimalEvaluationStatus.NOT_RUN
    )
    primal_evaluation_count: int = 0
    primal_evaluation_seconds: float = 0.0
    primal_objective_value: float | None = None
    served_passenger_count: int | None = None
    unserved_passenger_count: int | None = None
    primal_candidate_summaries: tuple[DddPrimalEvaluationSummary, ...] = ()
    trajectory_optimizer_mode: DddTrajectoryOptimizerMode = (
        DddTrajectoryOptimizerMode.OFF
    )
    trajectory_pool_status: DddTrajectorySlotPoolStatus | None = None
    trajectory_bound_status: DddTrajectoryBoundStatus | None = None
    trajectory_certified_lower_bound: float | None = None
    trajectory_pool_candidate_count: int = 0
    trajectory_pool_added_option_count: int = 0
    trajectory_pool_option_count: int = 0
    trajectory_pool_solved_this_round: bool = False
    trajectory_pool_option_cache_hit_count: int = 0
    trajectory_pool_option_cache_miss_count: int = 0
    trajectory_pool_option_cache_seconds: float = 0.0
    trajectory_pool_added_ride_variable_count: int = 0
    trajectory_pool_master_model_created: bool = False
    trajectory_pool_master_update_seconds: float = 0.0
    trajectory_pool_time_to_first_incumbent_seconds: float | None = None
    trajectory_pool_incumbent_improvement_count: int = 0
    trajectory_pool_ride_variable_count: int = 0
    trajectory_pool_conflict_round_count: int = 0
    trajectory_pool_incompatibility_count: int = 0
    trajectory_pool_seconds: float = 0.0
    trajectory_pool_lp_status: DddTrajectoryPassengerLpStatus | None = None
    trajectory_pool_lp_objective_value: float | None = None
    trajectory_pool_lp_dual_fingerprint: str | None = None
    trajectory_pool_lp_incompatibility_count: int = 0
    trajectory_pool_lp_row_separation_complete: bool = False
    trajectory_pool_lp_build_seconds: float = 0.0
    trajectory_pool_lp_optimize_seconds: float = 0.0
    trajectory_pool_lp_total_seconds: float = 0.0
    trajectory_pricing_status: DddCpSatPrimalStatus = DddCpSatPrimalStatus.NOT_RUN
    trajectory_pricing_preference_count: int = 0
    trajectory_pricing_candidate_count: int = 0
    trajectory_pricing_objective_value: float | None = None
    trajectory_pricing_objective_bound: float | None = None
    trajectory_pricing_signal_fingerprint: str | None = None
    trajectory_pricing_seconds: float = 0.0
    aggregate_support_constraint_count: int = 0
    aggregate_threshold_variable_count: int = 0
    timed_flow_cover_constraint_count: int = 0
    timed_flow_threshold_variable_count: int = 0
    fixed_start_structural_constraint_count: int = 0
    added_aggregate_support_cut_ids: tuple[str, ...] = ()
    cp_sat_core_literal_count: int = 0
    cp_sat_timed_flow_core_literal_count: int = 0
    cp_sat_timed_flow_core_resource_ids: tuple[str, ...] = ()
    cp_sat_local_explainability: DddCpSatLocalExplainabilityObservation | None = None
    added_timed_flow_cover_cut_ids: tuple[str, ...] = ()
    cp_sat_nearest_status: DddCpSatPrimalStatus = DddCpSatPrimalStatus.NOT_RUN
    cp_sat_nearest_seconds: float = 0.0
    cp_sat_nearest_distance_primal: int | None = None
    cp_sat_nearest_distance_lower_bound: float | None = None
    added_aggregate_distance_cut_ids: tuple[str, ...] = ()
    master_passenger_variable_count: int = 0
    master_passenger_constraint_count: int = 0
    master_served_passenger_count: float | None = None
    master_unserved_passenger_count: float | None = None
    master_solver_status_code: int | None = None
    master_termination_reason: str | None = None
    master_model_build_seconds: float = 0.0
    master_optimize_seconds: float = 0.0
    master_solution_count: int = 0
    master_explored_node_count: float = 0.0
    master_open_node_count: float = 0.0
    master_simplex_iteration_count: float = 0.0
    master_absolute_gap: float | None = None
    master_relative_gap: float | None = None
    master_time_to_first_incumbent_seconds: float | None = None
    master_incumbent_improvements: tuple[DddAnonymousMasterIncumbent, ...] = ()
    master_progress_snapshots: tuple[DddAnonymousMasterProgress, ...] = ()
    resource_window_resolve_count: int = 0
    resource_window_candidate_count: int = 0
    resource_window_violated_count: int = 0
    resource_window_duplicate_count: int = 0
    resource_window_added_count: int = 0
    resource_window_entry_row_count: int = 0
    resource_window_energy_row_count: int = 0
    resource_window_separation_seconds: float = 0.0
    resource_window_master_seconds: float = 0.0
    resource_window_lower_bound_before: float | None = None
    resource_window_lower_bound_after: float | None = None


@dataclass(frozen=True)
class DddNetworkTimeRefinementResult:
    status: DddNetworkTimeRefinementStatus
    schedules: tuple[DddRecoveredSchedule, ...]
    reference_solution: DddReferenceSolution | None
    global_lower_bound: float | None
    global_upper_bound: float | None
    absolute_gap: float | None
    iterations: tuple[DddNetworkTimeRefinementIteration, ...]
    final_discretization: DddTimeDiscretization
    conflict_cuts: tuple[DddSupportConflictCut, ...]
    primal_evaluation: DddPrimalEvaluationResult | None = None
    aggregate_support_cuts: tuple[DddAggregateSupportCut, ...] = ()
    aggregate_distance_cuts: tuple[DddAggregateSupportDistanceCut, ...] = ()
    timed_flow_cover_cuts: tuple[DddTimedFlowCoverCut, ...] = ()
    cp_sat_bootstrap_status: DddCpSatPrimalStatus = DddCpSatPrimalStatus.NOT_RUN
    cp_sat_bootstrap_seconds: float = 0.0
    cp_sat_bootstrap_candidate_count: int = 0
    cp_sat_bootstrap_objective: float | None = None
