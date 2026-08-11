from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import math
from time import perf_counter

from ropeway_skip_stop_optimization.optimization.ddd.aggregate_support import (
    DddAggregateSupportCut,
    DddAggregateSupportDistanceCut,
    DddCpSatFixedSupport,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_primal import (
    DddCpSatPrimalOracle,
    DddCpSatPrimalResult,
    DddCpSatPrimalStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.local_resource_explainability import (
    DddCpSatLocalExplainabilityObservation,
    DddCpSatLocalResourceAnalyzer,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddAnonymousFlowDecomposer,
    DddAnonymousFlowMaster,
    DddAnonymousFlowResult,
    DddAnonymousFlowWarmStart,
    DddAnonymousMasterIncumbent,
    DddAnonymousMasterProgress,
    DddAnonymousFlowStatus,
    DddAnonymousFlowWarmStartProjector,
    DddLayeredTimeArc,
    DddLayeredTimeArcKind,
    DddLayeredTimeNetwork,
    DddLayeredTimeNetworkBuilder,
    DddNetworkPathProblemAdapter,
    DddNetworkTimeProblem,
    build_ddd_cp_sat_timed_flow_support,
    estimate_ddd_prefix_formulation_size,
)
from ropeway_skip_stop_optimization.optimization.ddd.primal_evaluation import (
    DddPrimalPoolEvaluationResult,
    DddPrimalEvaluationResult,
    DddPrimalEvaluationSummary,
    DddPrimalEvaluationStatus,
    DddPrimalEvaluator,
)
from ropeway_skip_stop_optimization.optimization.ddd.passenger_master import (
    DddPassengerMasterProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_slot import (
    DddTrajectorySlotCandidate,
    DddTrajectorySlotPoolResult,
    DddTrajectorySlotPoolStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.resource_time import (
    DddAnonymousResourceRow,
    DddAnonymousResourceRowKind,
    DddResourceWindowCutMode,
    build_ddd_universal_resource_row,
    separate_ddd_resource_window_rows,
)
from ropeway_skip_stop_optimization.optimization.ddd.lifting import (
    build_ddd_cabin_path_core_cut,
    build_ddd_prefix_conflict_cuts,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceConflict,
    DddReferenceHorizonCoverageError,
    DddReferenceResourceConflictError,
    DddReferenceSolution,
    DddReferenceTrajectory,
    build_ddd_reference_visit,
    find_ddd_reference_conflicts,
    validate_ddd_reference_solution,
)
from ropeway_skip_stop_optimization.optimization.ddd.support_master import (
    DddSupportConflictCut,
    DddSupportSelection,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_refinement import (
    DddCellFreeSupportRecovery,
    DddEventCellInconsistency,
    DddPrimalRecoveryStatus,
    DddRecoveredSchedule,
    DddStrictTimeCellLifter,
    DddStrictTimeLiftStatus,
    DddTimeRefinementStalledError,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_space import (
    DddPartialTimedPath,
    DddTimeDiscretization,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_quantize_time_seconds,
    ddd_seconds_to_tick,
    ddd_tick_to_seconds,
)
from ropeway_skip_stop_optimization.optimization.ddd.timed_flow_cover import (
    DddTimedFlowCoverCut,
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


class DddCpSatMasterCoupling(StrEnum):
    FREE_ROUTE_CHOICES = "free_route_choices"
    FIXED_AGGREGATE_SUPPORT = "fixed_aggregate_support"


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
    trajectory_pool_status: DddTrajectorySlotPoolStatus | None = None
    trajectory_pool_option_count: int = 0
    trajectory_pool_ride_variable_count: int = 0
    trajectory_pool_conflict_round_count: int = 0
    trajectory_pool_incompatibility_count: int = 0
    trajectory_pool_seconds: float = 0.0
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


@dataclass(frozen=True)
class DddNetworkTimeRefinementSolver:
    max_iterations: int = 100
    tolerance_seconds: float = 1e-9
    bound_tolerance: float = 1e-9
    output_flag: bool = False
    max_new_cuts_per_iteration: int = 10_000
    max_new_time_splits_per_iteration: int = 1
    reuse_network_fragments: bool = True
    use_projected_warm_start: bool = True
    use_structural_earliest_times: bool = True
    use_mandatory_resource_rows: bool = True
    use_universal_resource_rows: bool = True
    resource_window_cut_mode: DddResourceWindowCutMode = (
        DddResourceWindowCutMode.OFF
    )
    max_resource_window_rows_per_resolve: int = 100
    max_resource_window_resolves_per_iteration: int = 10
    max_prefix_variable_count: int = 20_000
    max_tracked_prefix_cabin_count: int = 8
    max_prefix_visit_index: int = 3
    use_cp_sat_primal_oracle: bool = True
    cp_sat_time_limit_seconds: float = 5.0
    cp_sat_num_workers: int = 8
    cp_sat_retry_interval: int = 10
    cp_sat_max_candidate_count: int = 1
    cp_sat_minimum_hamming_distance: int = 1
    cp_sat_master_coupling: DddCpSatMasterCoupling = (
        DddCpSatMasterCoupling.FREE_ROUTE_CHOICES
    )
    use_cp_sat_primal_bootstrap: bool = True
    use_cp_sat_nearest_support: bool = True
    use_cp_sat_timed_flow_covers: bool = False
    use_cp_sat_cabin_path_cuts: bool = False
    collect_cp_sat_local_explainability: bool = False
    cp_sat_local_explainability_time_limit_seconds: float = 0.5
    cp_sat_nearest_support_time_limit_seconds: float = 5.0
    # The restricted trajectory pool is a passenger-objective primal
    # heuristic.  It must be enabled explicitly and is deliberately absent
    # from movement-only feasibility experiments.
    use_trajectory_slot_pool: bool = False

    def solve(
        self,
        problem: DddNetworkTimeProblem,
        *,
        progress_callback: DddNetworkTimeRefinementProgressCallback | None = None,
        primal_evaluator: DddPrimalEvaluator | None = None,
        passenger_master_problem: DddPassengerMasterProblem | None = None,
    ) -> DddNetworkTimeRefinementResult:
        problem.validate()
        if self.use_cp_sat_timed_flow_covers and self.cp_sat_master_coupling is not (
            DddCpSatMasterCoupling.FIXED_AGGREGATE_SUPPORT
        ):
            raise ValueError(
                "DDD timed-flow covers require fixed aggregate master coupling"
            )
        if self.use_cp_sat_cabin_path_cuts and not self.use_cp_sat_primal_oracle:
            raise ValueError("DDD cabin-path cuts require the CP-SAT primal oracle")
        if (
            self.collect_cp_sat_local_explainability
            and not self.use_cp_sat_timed_flow_covers
        ):
            raise ValueError(
                "DDD local CP-SAT explainability requires timed-flow covers"
            )
        if primal_evaluator is not None:
            primal_evaluator.validate_problem(problem)
        if passenger_master_problem is not None:
            passenger_master_problem.validate()
            if passenger_master_problem.movement_problem != problem.movement_problem:
                raise ValueError(
                    "DDD passenger master and refinement movement problems differ"
                )
            if primal_evaluator is None:
                raise ValueError(
                    "DDD passenger master requires exact passenger primal evaluation"
                )
            evaluator_objective = getattr(primal_evaluator, "objective", None)
            if (
                evaluator_objective is not None
                and evaluator_objective != passenger_master_problem.objective
            ):
                raise ValueError(
                    "DDD passenger master and primal evaluator objectives differ"
                )
            if any(
                not math.isclose(item.cost, 0.0, abs_tol=1e-12)
                for item in problem.objective.route_option_costs
            ):
                raise ValueError(
                    "DDD passenger master requires zero movement route costs"
                )
            if (
                self.cp_sat_master_coupling
                is not DddCpSatMasterCoupling.FIXED_AGGREGATE_SUPPORT
            ):
                raise ValueError(
                    "DDD passenger master requires fixed aggregate CP-SAT support"
                )
        if self.max_iterations <= 0:
            raise ValueError("DDD network refinement max_iterations must be positive")
        if self.max_new_cuts_per_iteration <= 0:
            raise ValueError(
                "DDD network refinement max_new_cuts_per_iteration must be positive"
            )
        if self.max_new_time_splits_per_iteration <= 0:
            raise ValueError(
                "DDD network refinement max_new_time_splits_per_iteration "
                "must be positive"
            )
        if not isinstance(self.resource_window_cut_mode, DddResourceWindowCutMode):
            raise ValueError("DDD resource-window cut mode is invalid")
        if self.max_resource_window_rows_per_resolve <= 0:
            raise ValueError("DDD resource-window row limit must be positive")
        if self.max_resource_window_resolves_per_iteration <= 0:
            raise ValueError("DDD resource-window resolve limit must be positive")
        if self.max_prefix_variable_count <= 0:
            raise ValueError("DDD prefix variable budget must be positive")
        if self.max_tracked_prefix_cabin_count <= 0:
            raise ValueError("DDD tracked-prefix cabin budget must be positive")
        if self.max_prefix_visit_index <= 0:
            raise ValueError("DDD prefix visit budget must be positive")
        if self.cp_sat_time_limit_seconds <= 0:
            raise ValueError("DDD CP-SAT time limit must be positive")
        if self.cp_sat_nearest_support_time_limit_seconds <= 0:
            raise ValueError("DDD nearest-support CP-SAT time limit must be positive")
        if self.cp_sat_local_explainability_time_limit_seconds <= 0:
            raise ValueError(
                "DDD local explainability CP-SAT time limit must be positive"
            )
        if self.cp_sat_num_workers <= 0:
            raise ValueError("DDD CP-SAT worker count must be positive")
        if self.cp_sat_retry_interval <= 0:
            raise ValueError("DDD CP-SAT retry interval must be positive")
        if self.cp_sat_max_candidate_count <= 0:
            raise ValueError("DDD CP-SAT candidate count must be positive")
        if self.cp_sat_minimum_hamming_distance <= 0:
            raise ValueError("DDD CP-SAT Hamming distance must be positive")
        if self.tolerance_seconds < 0 or self.bound_tolerance < 0:
            raise ValueError("DDD network refinement tolerances must be nonnegative")
        shared_builder = DddLayeredTimeNetworkBuilder(
            tolerance_seconds=self.tolerance_seconds,
            use_structural_earliest_times=self.use_structural_earliest_times,
        )
        master = DddAnonymousFlowMaster(
            output_flag=self.output_flag,
            include_mandatory_resource_rows=self.use_mandatory_resource_rows,
        )
        warm_start_projector = DddAnonymousFlowWarmStartProjector()
        decomposer = DddAnonymousFlowDecomposer()
        path_adapter = DddNetworkPathProblemAdapter()
        cell_lifter = DddStrictTimeCellLifter(tolerance_seconds=self.tolerance_seconds)
        recovery = DddCellFreeSupportRecovery(tolerance_seconds=self.tolerance_seconds)
        cp_sat_oracle = DddCpSatPrimalOracle(
            time_limit_seconds=self.cp_sat_time_limit_seconds,
            num_workers=self.cp_sat_num_workers,
            log_search_progress=self.output_flag,
            max_candidate_count=self.cp_sat_max_candidate_count,
            minimum_hamming_distance=self.cp_sat_minimum_hamming_distance,
        )
        nearest_support_oracle = DddCpSatPrimalOracle(
            time_limit_seconds=self.cp_sat_nearest_support_time_limit_seconds,
            num_workers=self.cp_sat_num_workers,
            log_search_progress=self.output_flag,
            max_candidate_count=1,
            minimum_hamming_distance=1,
        )
        local_resource_analyzer = DddCpSatLocalResourceAnalyzer(
            time_limit_seconds=(self.cp_sat_local_explainability_time_limit_seconds),
            num_workers=self.cp_sat_num_workers,
        )
        current = problem
        lower_bound = -math.inf
        upper_bound = math.inf
        best_schedules: tuple[DddRecoveredSchedule, ...] = ()
        best_reference: DddReferenceSolution | None = None
        best_primal_evaluation: DddPrimalEvaluationResult | None = None
        iterations: list[DddNetworkTimeRefinementIteration] = []
        cuts: list[DddSupportConflictCut] = []
        cut_ids: set[str] = set()
        aggregate_support_cuts: list[DddAggregateSupportCut] = []
        aggregate_support_cut_ids: set[str] = set()
        aggregate_distance_cuts: list[DddAggregateSupportDistanceCut] = []
        aggregate_distance_cut_ids: set[str] = set()
        timed_flow_cover_cuts: list[DddTimedFlowCoverCut] = []
        timed_flow_cover_cut_ids: set[str] = set()
        active_resource_rows: list[DddAnonymousResourceRow] = []
        active_resource_row_fingerprint: str | None = None
        universal_resource_row_ids: set[str] = set()
        interval_resource_row_ids: set[str] = set()
        previous_paths = ()
        solve_started = perf_counter()
        bootstrap_result = None
        bootstrap_objective: float | None = None

        def emit(
            stage: DddNetworkTimeRefinementProgressStage,
            round_index: int,
            *,
            iteration: DddNetworkTimeRefinementIteration | None = None,
            candidate_index: int | None = None,
            candidate_limit: int | None = None,
            candidate_elapsed_seconds: float | None = None,
            primal_best_objective: float | None = None,
            master_progress: DddAnonymousMasterProgress | None = None,
        ) -> None:
            if progress_callback is None:
                return
            progress_callback(
                DddNetworkTimeRefinementProgressEvent(
                    stage=stage,
                    round_index=round_index,
                    max_iterations=self.max_iterations,
                    total_elapsed_seconds=perf_counter() - solve_started,
                    iteration=iteration,
                    candidate_index=candidate_index,
                    candidate_limit=candidate_limit,
                    candidate_elapsed_seconds=candidate_elapsed_seconds,
                    primal_best_objective=primal_best_objective,
                    master_progress=master_progress,
                )
            )

        def record_iteration(
            iteration: DddNetworkTimeRefinementIteration,
        ) -> None:
            iterations.append(iteration)
            emit(
                DddNetworkTimeRefinementProgressStage.ROUND_FINISHED,
                iteration.round_index,
                iteration=iteration,
            )

        if (
            self.use_cp_sat_primal_oracle
            and self.use_cp_sat_primal_bootstrap
            and self.cp_sat_master_coupling
            is DddCpSatMasterCoupling.FIXED_AGGREGATE_SUPPORT
        ):
            emit(DddNetworkTimeRefinementProgressStage.PRIMAL_BOOTSTRAP_STARTED, 0)
            bootstrap_result = cp_sat_oracle.solve(current)
            if bootstrap_result.status is DddCpSatPrimalStatus.INFEASIBLE:
                emit(DddNetworkTimeRefinementProgressStage.PRIMAL_BOOTSTRAP_FINISHED, 0)
                return _result(
                    status=(
                        DddNetworkTimeRefinementStatus.INVALID_INTERNAL
                        if best_reference is not None
                        else DddNetworkTimeRefinementStatus.EXACT_INFEASIBLE
                    ),
                    schedules=best_schedules,
                    reference_solution=best_reference,
                    lower_bound=lower_bound,
                    upper_bound=math.inf,
                    iterations=iterations,
                    discretization=current.discretization,
                    cuts=cuts,
                    aggregate_support_cuts=aggregate_support_cuts,
                    aggregate_distance_cuts=aggregate_distance_cuts,
                    timed_flow_cover_cuts=timed_flow_cover_cuts,
                    bootstrap_result=bootstrap_result,
                )
            if bootstrap_result.status is DddCpSatPrimalStatus.FEASIBLE:
                bootstrap_candidates = (
                    bootstrap_result.candidate_schedules
                    if bootstrap_result.candidate_schedules
                    else (bootstrap_result.schedules,)
                )
                for candidate_schedules in bootstrap_candidates:
                    validation = _validate_reference_solution(
                        current,
                        candidate_schedules,
                        tolerance_seconds=self.tolerance_seconds,
                    )
                    if validation.solution is None:
                        emit(
                            DddNetworkTimeRefinementProgressStage.PRIMAL_BOOTSTRAP_FINISHED,
                            0,
                        )
                        return _result(
                            status=DddNetworkTimeRefinementStatus.INVALID_INTERNAL,
                            schedules=(),
                            reference_solution=None,
                            lower_bound=lower_bound,
                            upper_bound=math.inf,
                            iterations=iterations,
                            discretization=current.discretization,
                            cuts=cuts,
                            aggregate_support_cuts=aggregate_support_cuts,
                            aggregate_distance_cuts=aggregate_distance_cuts,
                            timed_flow_cover_cuts=timed_flow_cover_cuts,
                            bootstrap_result=bootstrap_result,
                        )
                    evaluation = (
                        primal_evaluator.evaluate(current, validation.solution)
                        if primal_evaluator is not None
                        else None
                    )
                    objective_value = (
                        evaluation.objective_value
                        if evaluation is not None
                        and evaluation.status is DddPrimalEvaluationStatus.FEASIBLE
                        else (
                            sum(item.objective_value for item in candidate_schedules)
                            if evaluation is None
                            else None
                        )
                    )
                    if objective_value is not None and objective_value < upper_bound:
                        upper_bound = objective_value
                        bootstrap_objective = objective_value
                        best_schedules = candidate_schedules
                        best_reference = validation.solution
                        best_primal_evaluation = evaluation
            emit(DddNetworkTimeRefinementProgressStage.PRIMAL_BOOTSTRAP_FINISHED, 0)

        for round_index in range(1, self.max_iterations + 1):
            round_started = perf_counter()
            primal_evaluation_status = DddPrimalEvaluationStatus.NOT_RUN
            primal_evaluation_count = 0
            primal_evaluation_seconds = 0.0
            round_primal_objective: float | None = None
            round_primal_evaluation: DddPrimalEvaluationResult | None = None
            primal_candidate_summaries: list[DddPrimalEvaluationSummary] = []
            trajectory_pool_candidates: list[DddTrajectorySlotCandidate] = []
            trajectory_pool_result: DddTrajectorySlotPoolResult | None = None

            def consider_primal_candidate(
                schedules: tuple[DddRecoveredSchedule, ...],
                solution: DddReferenceSolution,
            ) -> None:
                nonlocal best_primal_evaluation
                nonlocal best_reference
                nonlocal best_schedules
                nonlocal primal_evaluation_count
                nonlocal primal_evaluation_seconds
                nonlocal primal_evaluation_status
                nonlocal round_primal_evaluation
                nonlocal round_primal_objective
                nonlocal upper_bound

                evaluation: DddPrimalEvaluationResult | None = None
                if primal_evaluator is None:
                    objective_value = sum(
                        schedule.objective_value for schedule in schedules
                    )
                else:
                    evaluation = primal_evaluator.evaluate(current, solution)
                    primal_candidate_summaries.append(evaluation.summary)
                    primal_evaluation_count += 1
                    primal_evaluation_seconds += evaluation.total_seconds
                    if evaluation.status is DddPrimalEvaluationStatus.FEASIBLE:
                        primal_evaluation_status = DddPrimalEvaluationStatus.FEASIBLE
                    elif primal_evaluation_status is DddPrimalEvaluationStatus.NOT_RUN:
                        primal_evaluation_status = evaluation.status
                    objective_value = evaluation.objective_value
                    emit(
                        DddNetworkTimeRefinementProgressStage.PRIMAL_EVALUATION_FINISHED,
                        round_index,
                        candidate_index=primal_evaluation_count,
                        candidate_limit=cp_sat_candidate_count,
                        candidate_elapsed_seconds=primal_evaluation_seconds,
                        primal_best_objective=(
                            min(upper_bound, objective_value)
                            if objective_value is not None
                            else _finite_or_none(upper_bound)
                        ),
                    )
                    if (
                        evaluation.status is not DddPrimalEvaluationStatus.FEASIBLE
                        or objective_value is None
                    ):
                        return
                    if evaluation.movement_plan is None:
                        raise RuntimeError(
                            "feasible DDD primal evaluation has no movement plan"
                        )
                    trajectory_pool_candidates.append(
                        DddTrajectorySlotCandidate(
                            schedules=schedules,
                            reference_solution=solution,
                            movement_plan=evaluation.movement_plan,
                        )
                    )
                    if (
                        round_primal_objective is None
                        or objective_value < round_primal_objective
                    ):
                        round_primal_objective = objective_value
                        round_primal_evaluation = evaluation
                if objective_value < upper_bound:
                    upper_bound = objective_value
                    best_schedules = schedules
                    best_reference = solution
                    best_primal_evaluation = evaluation

            emit(
                DddNetworkTimeRefinementProgressStage.ROUND_STARTED,
                round_index,
            )
            if active_resource_row_fingerprint != current.discretization.fingerprint:
                active_resource_rows.clear()
                active_resource_row_fingerprint = current.discretization.fingerprint
            network_started = perf_counter()
            builder = (
                shared_builder
                if self.reuse_network_fragments
                else DddLayeredTimeNetworkBuilder(
                    tolerance_seconds=self.tolerance_seconds,
                    use_structural_earliest_times=(self.use_structural_earliest_times),
                )
            )
            network = builder.build(current)
            network_build_seconds = perf_counter() - network_started
            if not _prefix_formulation_within_budget(
                network,
                tuple(cuts),
                max_variable_count=self.max_prefix_variable_count,
                max_cabin_count=self.max_tracked_prefix_cabin_count,
                max_visit_index=self.max_prefix_visit_index,
            ):
                return _result(
                    status=(DddNetworkTimeRefinementStatus.REFINEMENT_BUDGET_EXHAUSTED),
                    schedules=best_schedules,
                    reference_solution=best_reference,
                    lower_bound=lower_bound,
                    upper_bound=upper_bound,
                    iterations=iterations,
                    discretization=current.discretization,
                    cuts=cuts,
                    primal_evaluation=best_primal_evaluation,
                    aggregate_support_cuts=aggregate_support_cuts,
                    aggregate_distance_cuts=aggregate_distance_cuts,
                    timed_flow_cover_cuts=timed_flow_cover_cuts,
                    bootstrap_result=bootstrap_result,
                    bootstrap_objective=bootstrap_objective,
                )
            emit(
                DddNetworkTimeRefinementProgressStage.NETWORK_BUILT,
                round_index,
            )
            active_cuts = tuple(cuts)
            warm_start = (
                warm_start_projector.project(
                    current,
                    network,
                    previous_paths,
                    cuts=active_cuts,
                )
                if self.use_projected_warm_start and previous_paths
                else None
            )
            resource_windows = tuple(
                window for arc in network.arcs for window in arc.resource_windows
            )
            round_resource_window_rows: list[DddAnonymousResourceRow] = []
            resource_window_resolve_count = 0
            resource_window_candidate_count = 0
            resource_window_violated_count = 0
            resource_window_duplicate_count = 0
            resource_window_entry_row_count = 0
            resource_window_energy_row_count = 0
            resource_window_separation_seconds = 0.0
            resource_window_master_seconds = 0.0
            resource_window_lower_bound_before: float | None = None
            resource_window_lower_bound_after: float | None = None
            master_solve_seconds = 0.0
            while True:
                emit(
                    DddNetworkTimeRefinementProgressStage.MASTER_STARTED,
                    round_index,
                )
                master_started = perf_counter()
                flow = master.solve(
                    network,
                    cuts=active_cuts,
                    aggregate_support_cuts=tuple(aggregate_support_cuts),
                    aggregate_distance_cuts=tuple(aggregate_distance_cuts),
                    timed_flow_cover_cuts=tuple(timed_flow_cover_cuts),
                    resource_rows=tuple(active_resource_rows),
                    warm_start=warm_start,
                    passenger_problem=passenger_master_problem,
                    fixed_start_movement_problem=(
                        current.movement_problem
                        if self.cp_sat_master_coupling
                        is DddCpSatMasterCoupling.FIXED_AGGREGATE_SUPPORT
                        else None
                    ),
                    progress_callback=lambda item: emit(
                        DddNetworkTimeRefinementProgressStage.MASTER_PROGRESS,
                        round_index,
                        master_progress=item,
                    ),
                )
                solve_seconds = perf_counter() - master_started
                master_solve_seconds += solve_seconds
                if resource_window_resolve_count:
                    resource_window_master_seconds += solve_seconds
                emit(
                    DddNetworkTimeRefinementProgressStage.MASTER_FINISHED,
                    round_index,
                )
                if flow.status is DddAnonymousFlowStatus.INFEASIBLE:
                    break
                if flow.best_bound is None:
                    raise RuntimeError("optimal DDD network flow returned no best bound")
                if resource_window_lower_bound_before is None:
                    resource_window_lower_bound_before = flow.best_bound
                resource_window_lower_bound_after = flow.best_bound
                if self.resource_window_cut_mode is DddResourceWindowCutMode.OFF:
                    break

                separation_started = perf_counter()
                separation = separate_ddd_resource_window_rows(
                    resource_windows,
                    arc_flow_by_id={
                        item.arc_id: item.value for item in flow.arc_values
                    },
                    mode=self.resource_window_cut_mode,
                    max_rows=self.max_resource_window_rows_per_resolve,
                )
                resource_window_separation_seconds += (
                    perf_counter() - separation_started
                )
                resource_window_candidate_count += separation.candidate_window_count
                resource_window_violated_count += separation.violated_candidate_count
                resource_window_duplicate_count += separation.duplicate_candidate_count
                active_resource_row_ids = {row.id for row in active_resource_rows}
                new_rows = tuple(
                    row
                    for row in separation.rows
                    if row.id not in active_resource_row_ids
                )
                resource_window_duplicate_count += len(separation.rows) - len(new_rows)
                emit(
                    DddNetworkTimeRefinementProgressStage.RESOURCE_WINDOW_SEPARATION_FINISHED,
                    round_index,
                )
                if (
                    not new_rows
                    or resource_window_resolve_count
                    >= self.max_resource_window_resolves_per_iteration
                ):
                    break
                active_resource_rows.extend(new_rows)
                round_resource_window_rows.extend(new_rows)
                interval_resource_row_ids.update(row.id for row in new_rows)
                resource_window_entry_row_count += sum(
                    row.kind is DddAnonymousResourceRowKind.INTERVAL_CAPACITY
                    for row in new_rows
                )
                resource_window_energy_row_count += sum(
                    row.kind is DddAnonymousResourceRowKind.INTERVAL_ENERGY
                    for row in new_rows
                )
                resource_window_resolve_count += 1
                warm_start = DddAnonymousFlowWarmStart(
                    arc_values=flow.arc_values,
                    prefix_arc_values=flow.prefix_arc_values,
                    projected_cabin_count=len(network.cabin_ids),
                    complete_cabin_count=0,
                )
            if flow.status is DddAnonymousFlowStatus.INFEASIBLE:
                record_iteration(
                    _iteration(
                        round_index=round_index,
                        problem=current,
                        node_count=len(network.nodes),
                        arc_count=len(network.arcs),
                        variable_count=flow.variable_count,
                        constraint_count=flow.constraint_count,
                        prefix_variable_count=flow.prefix_variable_count,
                        conflict_constraint_count=flow.conflict_constraint_count,
                        resource_constraint_count=(flow.resource_constraint_count),
                        mandatory_resource_constraint_count=(
                            flow.mandatory_resource_constraint_count
                        ),
                        additional_resource_constraint_count=(
                            flow.additional_resource_constraint_count
                        ),
                        added_resource_row_ids=tuple(
                            row.id for row in round_resource_window_rows
                        ),
                        total_universal_resource_row_count=len(
                            universal_resource_row_ids
                        ),
                        total_interval_resource_row_count=len(
                            interval_resource_row_ids
                        ),
                        tracked_prefix_cabin_count=(flow.tracked_prefix_cabin_count),
                        warm_start_arc_variable_count=(
                            flow.warm_start_arc_variable_count
                        ),
                        warm_start_prefix_variable_count=(
                            flow.warm_start_prefix_variable_count
                        ),
                        warm_start_projected_cabin_count=(
                            flow.warm_start_projected_cabin_count
                        ),
                        warm_start_complete_cabin_count=(
                            flow.warm_start_complete_cabin_count
                        ),
                        path_count=0,
                        master_bound=None,
                        lower_bound=lower_bound,
                        recovery_feasible=False,
                        recovery_objective=None,
                        recovery_validation_status=(DddNetworkValidationStatus.NOT_RUN),
                        upper_bound=upper_bound,
                        cell_lift_statuses=(),
                        cell_lift_validation=_not_run_validation(),
                        conflict_count=0,
                        added_cut_ids=(),
                        total_conflict_cut_count=len(cuts),
                        time_splits=(),
                        trajectory_time_split_count=0,
                        resource_time_split_count=0,
                        cuts=active_cuts,
                        network_partition_cache_hits=(
                            builder.last_build_stats.partition_cache_hits
                        ),
                        network_partition_cache_misses=(
                            builder.last_build_stats.partition_cache_misses
                        ),
                        network_transition_cache_hits=(
                            builder.last_build_stats.transition_cache_hits
                        ),
                        network_transition_cache_misses=(
                            builder.last_build_stats.transition_cache_misses
                        ),
                        network_invalidated_state_count=(
                            builder.last_build_stats.invalidated_state_count
                        ),
                        network_build_seconds=network_build_seconds,
                        master_solve_seconds=master_solve_seconds,
                        decomposition_seconds=0.0,
                        recovery_seconds=0.0,
                        lifting_and_validation_seconds=0.0,
                        round_seconds=perf_counter() - round_started,
                        cp_sat_status=DddCpSatPrimalStatus.NOT_RUN,
                        cp_sat_seconds=0.0,
                        cp_sat_conflict_count=0,
                        cp_sat_branch_count=0,
                        cp_sat_candidate_count=0,
                        cp_sat_search_complete=False,
                        primal_evaluation_status=primal_evaluation_status,
                        primal_evaluation_count=primal_evaluation_count,
                        primal_evaluation_seconds=primal_evaluation_seconds,
                        primal_objective_value=round_primal_objective,
                        served_passenger_count=(
                            round_primal_evaluation.served_passenger_count
                            if round_primal_evaluation is not None
                            else None
                        ),
                        unserved_passenger_count=(
                            round_primal_evaluation.unserved_passenger_count
                            if round_primal_evaluation is not None
                            else None
                        ),
                        primal_candidate_summaries=tuple(primal_candidate_summaries),
                        aggregate_support_constraint_count=(
                            flow.aggregate_support_constraint_count
                        ),
                        aggregate_threshold_variable_count=(
                            flow.aggregate_threshold_variable_count
                        ),
                        fixed_start_structural_constraint_count=(
                            flow.fixed_start_structural_constraint_count
                        ),
                        master_passenger_variable_count=0,
                        master_passenger_constraint_count=0,
                        resource_window_resolve_count=(
                            resource_window_resolve_count
                        ),
                        resource_window_candidate_count=(
                            resource_window_candidate_count
                        ),
                        resource_window_violated_count=(
                            resource_window_violated_count
                        ),
                        resource_window_duplicate_count=(
                            resource_window_duplicate_count
                        ),
                        resource_window_added_count=len(round_resource_window_rows),
                        resource_window_entry_row_count=(
                            resource_window_entry_row_count
                        ),
                        resource_window_energy_row_count=(
                            resource_window_energy_row_count
                        ),
                        resource_window_separation_seconds=(
                            resource_window_separation_seconds
                        ),
                        resource_window_master_seconds=(
                            resource_window_master_seconds
                        ),
                        resource_window_lower_bound_before=(
                            resource_window_lower_bound_before
                        ),
                        resource_window_lower_bound_after=(
                            resource_window_lower_bound_after
                        ),
                        **_master_diagnostic_kwargs(flow),
                    )
                )
                return _result(
                    status=(
                        DddNetworkTimeRefinementStatus.INVALID_INTERNAL
                        if best_reference is not None
                        else DddNetworkTimeRefinementStatus.RELAXATION_INFEASIBLE
                    ),
                    schedules=best_schedules,
                    reference_solution=best_reference,
                    lower_bound=lower_bound,
                    upper_bound=upper_bound,
                    iterations=iterations,
                    discretization=current.discretization,
                    cuts=cuts,
                    primal_evaluation=best_primal_evaluation,
                    aggregate_support_cuts=aggregate_support_cuts,
                    aggregate_distance_cuts=aggregate_distance_cuts,
                    timed_flow_cover_cuts=timed_flow_cover_cuts,
                    bootstrap_result=bootstrap_result,
                    bootstrap_objective=bootstrap_objective,
                )
            lower_bound = max(lower_bound, flow.best_bound)
            decomposition_started = perf_counter()
            paths = decomposer.decompose(network, flow)
            previous_paths = paths
            path_problems = tuple(path_adapter.build(current, path) for path in paths)
            decomposition_seconds = perf_counter() - decomposition_started
            emit(
                DddNetworkTimeRefinementProgressStage.DECOMPOSITION_FINISHED,
                round_index,
            )

            cp_sat_status = DddCpSatPrimalStatus.NOT_RUN
            cp_sat_seconds = 0.0
            cp_sat_conflict_count = 0
            cp_sat_branch_count = 0
            cp_sat_candidate_count = 0
            cp_sat_search_complete = False
            cp_sat_exact_infeasible = False
            cp_sat_cabin_path_status = DddCpSatPrimalStatus.NOT_RUN
            cp_sat_cabin_path_seconds = 0.0
            cp_sat_cabin_path_core_cabin_ids: tuple[int, ...] = ()
            cp_sat_cabin_path_core_literal_count = 0
            cp_sat_cabin_path_cut_literal_count = 0
            cp_sat_cabin_path_candidate_cuts: tuple[DddSupportConflictCut, ...] = ()
            fixed_cp_support = (
                DddCpSatFixedSupport.from_paths(paths)
                if self.cp_sat_master_coupling
                is DddCpSatMasterCoupling.FIXED_AGGREGATE_SUPPORT
                else None
            )
            timed_flow_cp_support = (
                build_ddd_cp_sat_timed_flow_support(
                    network,
                    flow,
                    current.movement_problem,
                )
                if fixed_cp_support is not None and self.use_cp_sat_timed_flow_covers
                else None
            )
            new_aggregate_support_cuts: tuple[DddAggregateSupportCut, ...] = ()
            new_aggregate_distance_cuts: tuple[DddAggregateSupportDistanceCut, ...] = ()
            new_timed_flow_cover_cuts: tuple[DddTimedFlowCoverCut, ...] = ()
            cp_sat_core_literal_count = 0
            cp_sat_timed_flow_core_literal_count = 0
            cp_sat_timed_flow_core_resource_ids: tuple[str, ...] = ()
            cp_sat_local_explainability: (
                DddCpSatLocalExplainabilityObservation | None
            ) = None
            cp_sat_nearest_status = DddCpSatPrimalStatus.NOT_RUN
            cp_sat_nearest_seconds = 0.0
            cp_sat_nearest_distance_primal: int | None = None
            cp_sat_nearest_distance_lower_bound: float | None = None
            if self.use_cp_sat_primal_oracle and (
                self.cp_sat_master_coupling
                is DddCpSatMasterCoupling.FIXED_AGGREGATE_SUPPORT
                or round_index == 1
                or (
                    best_reference is None
                    and (round_index - 1) % self.cp_sat_retry_interval == 0
                )
            ):
                cp_result: DddCpSatPrimalResult | None = None
                if self.use_cp_sat_cabin_path_cuts:
                    cabin_path_result = cp_sat_oracle.solve(
                        current,
                        hint_paths=paths,
                        fixed_cabin_paths=paths,
                    )
                    cp_sat_cabin_path_status = cabin_path_result.status
                    cp_sat_cabin_path_seconds = cabin_path_result.wall_seconds
                    cp_sat_cabin_path_core_cabin_ids = tuple(
                        sorted(
                            {
                                literal.cabin_id
                                for literal in (
                                    cabin_path_result.cabin_path_infeasible_core
                                )
                            }
                        )
                    )
                    if cabin_path_result.cabin_path_infeasible_core:
                        cp_sat_cabin_path_core_literal_count = len(
                            cabin_path_result.cabin_path_infeasible_core
                        )
                        cabin_path_cut = build_ddd_cabin_path_core_cut(
                            paths,
                            cabin_path_result.cabin_path_infeasible_core,
                        )
                        cp_sat_cabin_path_cut_literal_count = len(
                            cabin_path_cut.literals
                        )
                        admissible_cuts, _ = _select_prefix_cuts_within_budget(
                            network,
                            tuple(cuts),
                            (cabin_path_cut,),
                            max_new_cuts=1,
                            max_variable_count=self.max_prefix_variable_count,
                            max_cabin_count=self.max_tracked_prefix_cabin_count,
                            max_visit_index=self.max_prefix_visit_index,
                        )
                        if admissible_cuts:
                            cp_sat_cabin_path_candidate_cuts = admissible_cuts
                            cp_result = cabin_path_result
                    elif cabin_path_result.status is not DddCpSatPrimalStatus.UNKNOWN:
                        cp_result = cabin_path_result
                if cp_result is None:
                    cp_result = cp_sat_oracle.solve(
                        current,
                        hint_paths=paths,
                        fixed_support=(
                            fixed_cp_support
                            if timed_flow_cp_support is None
                            else None
                        ),
                        timed_flow_support=timed_flow_cp_support,
                        candidate_callback=(
                            lambda candidate_index, elapsed_seconds: emit(
                                DddNetworkTimeRefinementProgressStage.PRIMAL_ORACLE_CANDIDATE_FOUND,
                                round_index,
                                candidate_index=candidate_index,
                                candidate_limit=self.cp_sat_max_candidate_count,
                                candidate_elapsed_seconds=elapsed_seconds,
                            )
                        ),
                    )
                cp_sat_status = cp_result.status
                cp_sat_seconds = cp_result.wall_seconds
                cp_sat_conflict_count = cp_result.conflict_count
                cp_sat_branch_count = cp_result.branch_count
                cp_sat_candidate_count = len(cp_result.candidate_schedules)
                cp_sat_search_complete = cp_result.search_complete
                if cp_result.status is DddCpSatPrimalStatus.FEASIBLE:
                    candidates = (
                        cp_result.candidate_schedules
                        if cp_result.candidate_schedules
                        else (cp_result.schedules,)
                    )
                    for candidate_schedules in candidates:
                        cp_validation = _validate_reference_solution(
                            current,
                            candidate_schedules,
                            tolerance_seconds=self.tolerance_seconds,
                        )
                        if cp_validation.solution is None:
                            return _result(
                                status=(
                                    DddNetworkTimeRefinementStatus.INVALID_INTERNAL
                                ),
                                schedules=best_schedules,
                                reference_solution=best_reference,
                                lower_bound=lower_bound,
                                upper_bound=upper_bound,
                                iterations=iterations,
                                discretization=current.discretization,
                                cuts=cuts,
                                primal_evaluation=best_primal_evaluation,
                                aggregate_support_cuts=aggregate_support_cuts,
                                aggregate_distance_cuts=aggregate_distance_cuts,
                                timed_flow_cover_cuts=timed_flow_cover_cuts,
                                bootstrap_result=bootstrap_result,
                                bootstrap_objective=bootstrap_objective,
                            )
                        consider_primal_candidate(
                            candidate_schedules,
                            cp_validation.solution,
                        )
                elif cp_result.status is DddCpSatPrimalStatus.INFEASIBLE:
                    cp_sat_core_literal_count = len(cp_result.infeasible_core)
                    cp_sat_timed_flow_core_literal_count = len(
                        cp_result.timed_flow_infeasible_core
                    )
                    support_rejected = False
                    if cp_result.cabin_path_infeasible_core:
                        support_rejected = True
                    elif cp_result.fixed_cabin_paths:
                        cp_sat_exact_infeasible = True
                    elif timed_flow_cp_support is not None:
                        if not cp_result.timed_flow_infeasible_core:
                            # No timed-flow assumption is needed for the proof:
                            # the unrestricted physical model itself is infeasible.
                            cp_sat_exact_infeasible = True
                        else:
                            timed_cut = DddTimedFlowCoverCut.from_core(
                                cp_result.timed_flow_infeasible_core
                            )
                            cp_sat_timed_flow_core_resource_ids = timed_cut.resource_ids
                            if self.collect_cp_sat_local_explainability:
                                cp_sat_local_explainability = (
                                    local_resource_analyzer.analyze(
                                        current,
                                        round_index=round_index,
                                        full_support=timed_flow_cp_support,
                                        core=cp_result.timed_flow_infeasible_core,
                                        hint_schedules=best_schedules,
                                    )
                                )
                            if timed_cut.id not in timed_flow_cover_cut_ids:
                                timed_flow_cover_cuts.append(timed_cut)
                                timed_flow_cover_cut_ids.add(timed_cut.id)
                                new_timed_flow_cover_cuts = (timed_cut,)
                            support_rejected = True
                    elif fixed_cp_support is None or not cp_result.infeasible_core:
                        cp_sat_exact_infeasible = True
                    else:
                        aggregate_cut = DddAggregateSupportCut.from_core(
                            cp_result.infeasible_core
                        )
                        if aggregate_cut.id not in aggregate_support_cut_ids:
                            aggregate_support_cuts.append(aggregate_cut)
                            aggregate_support_cut_ids.add(aggregate_cut.id)
                            new_aggregate_support_cuts = (aggregate_cut,)
                        support_rejected = True
                    if (
                        support_rejected
                        and not cp_result.fixed_cabin_paths
                        and self.use_cp_sat_nearest_support
                    ):
                        if fixed_cp_support is None:
                            raise RuntimeError(
                                "DDD rejected support has no aggregate nearest center"
                            )
                        nearest_result = nearest_support_oracle.solve(
                            current,
                            hint_schedules=best_schedules,
                            nearest_support=fixed_cp_support,
                        )
                        cp_sat_nearest_status = nearest_result.status
                        cp_sat_nearest_seconds = nearest_result.wall_seconds
                        cp_sat_nearest_distance_primal = (
                            nearest_result.support_distance_primal
                        )
                        cp_sat_nearest_distance_lower_bound = (
                            nearest_result.support_distance_lower_bound
                        )
                        if nearest_result.status is DddCpSatPrimalStatus.INFEASIBLE:
                            cp_sat_exact_infeasible = True
                        elif nearest_result.status is DddCpSatPrimalStatus.FEASIBLE:
                            nearest_validation = _validate_reference_solution(
                                current,
                                nearest_result.schedules,
                                tolerance_seconds=self.tolerance_seconds,
                            )
                            if nearest_validation.solution is None:
                                return _result(
                                    status=(
                                        DddNetworkTimeRefinementStatus.INVALID_INTERNAL
                                    ),
                                    schedules=best_schedules,
                                    reference_solution=best_reference,
                                    lower_bound=lower_bound,
                                    upper_bound=upper_bound,
                                    iterations=iterations,
                                    discretization=current.discretization,
                                    cuts=cuts,
                                    primal_evaluation=best_primal_evaluation,
                                    aggregate_support_cuts=(aggregate_support_cuts),
                                    aggregate_distance_cuts=(aggregate_distance_cuts),
                                    timed_flow_cover_cuts=timed_flow_cover_cuts,
                                    bootstrap_result=bootstrap_result,
                                    bootstrap_objective=bootstrap_objective,
                                )
                            consider_primal_candidate(
                                nearest_result.schedules,
                                nearest_validation.solution,
                            )
                            distance_bound = nearest_result.support_distance_lower_bound
                            if distance_bound is not None:
                                certified_distance = max(
                                    0,
                                    math.ceil(distance_bound - 1e-6),
                                )
                                if certified_distance > 0:
                                    distance_cut = (
                                        DddAggregateSupportDistanceCut.from_center(
                                            nearest_result.distance_center,
                                            minimum_distance=certified_distance,
                                        )
                                    )
                                    if (
                                        distance_cut.id
                                        not in aggregate_distance_cut_ids
                                    ):
                                        aggregate_distance_cuts.append(distance_cut)
                                        aggregate_distance_cut_ids.add(distance_cut.id)
                                        new_aggregate_distance_cuts = (distance_cut,)
                emit(
                    DddNetworkTimeRefinementProgressStage.PRIMAL_ORACLE_FINISHED,
                    round_index,
                )

            new_cabin_path_core_cuts = tuple(
                cut
                for cut in cp_sat_cabin_path_candidate_cuts
                if cut.id not in cut_ids
            )
            cuts.extend(new_cabin_path_core_cuts)
            cut_ids.update(cut.id for cut in new_cabin_path_core_cuts)

            if cp_sat_exact_infeasible and cp_sat_nearest_status is (
                DddCpSatPrimalStatus.INFEASIBLE
            ):
                return _result(
                    status=(
                        DddNetworkTimeRefinementStatus.INVALID_INTERNAL
                        if best_reference is not None
                        else DddNetworkTimeRefinementStatus.EXACT_INFEASIBLE
                    ),
                    schedules=best_schedules,
                    reference_solution=best_reference,
                    lower_bound=lower_bound,
                    upper_bound=(
                        upper_bound if best_reference is not None else math.inf
                    ),
                    iterations=iterations,
                    discretization=current.discretization,
                    cuts=cuts,
                    aggregate_support_cuts=aggregate_support_cuts,
                    aggregate_distance_cuts=aggregate_distance_cuts,
                    timed_flow_cover_cuts=timed_flow_cover_cuts,
                    bootstrap_result=bootstrap_result,
                    bootstrap_objective=bootstrap_objective,
                )

            # A fixed-support CP core already proves that no physical timing of
            # the current aggregate route counts exists.  Recovering and
            # splitting time cells for that dead support cannot make it
            # liftable; it only grows the next passenger master.  Add the
            # logic-based cut and re-solve the unchanged discretization.
            if (
                new_aggregate_support_cuts
                or new_aggregate_distance_cuts
                or new_timed_flow_cover_cuts
                or new_cabin_path_core_cuts
            ):
                record_iteration(
                    _iteration(
                        round_index=round_index,
                        problem=current,
                        node_count=len(network.nodes),
                        arc_count=len(network.arcs),
                        variable_count=flow.variable_count,
                        constraint_count=flow.constraint_count,
                        prefix_variable_count=flow.prefix_variable_count,
                        conflict_constraint_count=flow.conflict_constraint_count,
                        resource_constraint_count=flow.resource_constraint_count,
                        mandatory_resource_constraint_count=(
                            flow.mandatory_resource_constraint_count
                        ),
                        additional_resource_constraint_count=(
                            flow.additional_resource_constraint_count
                        ),
                        added_resource_row_ids=tuple(
                            row.id for row in round_resource_window_rows
                        ),
                        total_universal_resource_row_count=len(
                            universal_resource_row_ids
                        ),
                        total_interval_resource_row_count=len(
                            interval_resource_row_ids
                        ),
                        tracked_prefix_cabin_count=(flow.tracked_prefix_cabin_count),
                        warm_start_arc_variable_count=(
                            flow.warm_start_arc_variable_count
                        ),
                        warm_start_prefix_variable_count=(
                            flow.warm_start_prefix_variable_count
                        ),
                        warm_start_projected_cabin_count=(
                            flow.warm_start_projected_cabin_count
                        ),
                        warm_start_complete_cabin_count=(
                            flow.warm_start_complete_cabin_count
                        ),
                        path_count=len(paths),
                        master_bound=flow.best_bound,
                        lower_bound=lower_bound,
                        recovery_feasible=False,
                        recovery_objective=None,
                        recovery_validation_status=(DddNetworkValidationStatus.NOT_RUN),
                        upper_bound=upper_bound,
                        cell_lift_statuses=(),
                        cell_lift_validation=_not_run_validation(),
                        conflict_count=0,
                        added_cut_ids=tuple(
                            cut.id for cut in new_cabin_path_core_cuts
                        ),
                        total_conflict_cut_count=len(cuts),
                        time_splits=(),
                        trajectory_time_split_count=0,
                        resource_time_split_count=0,
                        cuts=active_cuts,
                        network_partition_cache_hits=(
                            builder.last_build_stats.partition_cache_hits
                        ),
                        network_partition_cache_misses=(
                            builder.last_build_stats.partition_cache_misses
                        ),
                        network_transition_cache_hits=(
                            builder.last_build_stats.transition_cache_hits
                        ),
                        network_transition_cache_misses=(
                            builder.last_build_stats.transition_cache_misses
                        ),
                        network_invalidated_state_count=(
                            builder.last_build_stats.invalidated_state_count
                        ),
                        network_build_seconds=network_build_seconds,
                        master_solve_seconds=master_solve_seconds,
                        decomposition_seconds=decomposition_seconds,
                        recovery_seconds=0.0,
                        lifting_and_validation_seconds=0.0,
                        round_seconds=perf_counter() - round_started,
                        cp_sat_status=cp_sat_status,
                        cp_sat_seconds=cp_sat_seconds,
                        cp_sat_conflict_count=cp_sat_conflict_count,
                        cp_sat_branch_count=cp_sat_branch_count,
                        cp_sat_candidate_count=cp_sat_candidate_count,
                        cp_sat_search_complete=cp_sat_search_complete,
                        cp_sat_cabin_path_status=cp_sat_cabin_path_status,
                        cp_sat_cabin_path_seconds=cp_sat_cabin_path_seconds,
                        cp_sat_cabin_path_core_cabin_ids=(
                            cp_sat_cabin_path_core_cabin_ids
                        ),
                        cp_sat_cabin_path_core_literal_count=(
                            cp_sat_cabin_path_core_literal_count
                        ),
                        cp_sat_cabin_path_cut_literal_count=(
                            cp_sat_cabin_path_cut_literal_count
                        ),
                        added_cabin_path_core_cut_ids=tuple(
                            cut.id for cut in new_cabin_path_core_cuts
                        ),
                        primal_evaluation_status=primal_evaluation_status,
                        primal_evaluation_count=primal_evaluation_count,
                        primal_evaluation_seconds=primal_evaluation_seconds,
                        primal_objective_value=round_primal_objective,
                        served_passenger_count=None,
                        unserved_passenger_count=None,
                        primal_candidate_summaries=(),
                        aggregate_support_constraint_count=(
                            flow.aggregate_support_constraint_count
                        ),
                        aggregate_threshold_variable_count=(
                            flow.aggregate_threshold_variable_count
                        ),
                        timed_flow_cover_constraint_count=(
                            flow.timed_flow_cover_constraint_count
                        ),
                        timed_flow_threshold_variable_count=(
                            flow.timed_flow_threshold_variable_count
                        ),
                        fixed_start_structural_constraint_count=(
                            flow.fixed_start_structural_constraint_count
                        ),
                        added_aggregate_support_cut_ids=tuple(
                            cut.id for cut in new_aggregate_support_cuts
                        ),
                        cp_sat_core_literal_count=cp_sat_core_literal_count,
                        cp_sat_timed_flow_core_literal_count=(
                            cp_sat_timed_flow_core_literal_count
                        ),
                        cp_sat_timed_flow_core_resource_ids=(
                            cp_sat_timed_flow_core_resource_ids
                        ),
                        cp_sat_local_explainability=cp_sat_local_explainability,
                        added_timed_flow_cover_cut_ids=tuple(
                            cut.id for cut in new_timed_flow_cover_cuts
                        ),
                        cp_sat_nearest_status=cp_sat_nearest_status,
                        cp_sat_nearest_seconds=cp_sat_nearest_seconds,
                        cp_sat_nearest_distance_primal=(cp_sat_nearest_distance_primal),
                        cp_sat_nearest_distance_lower_bound=(
                            cp_sat_nearest_distance_lower_bound
                        ),
                        added_aggregate_distance_cut_ids=tuple(
                            cut.id for cut in new_aggregate_distance_cuts
                        ),
                        master_passenger_variable_count=(
                            flow.passenger_solution.variable_count
                            if flow.passenger_solution is not None
                            else 0
                        ),
                        master_passenger_constraint_count=(
                            flow.passenger_solution.constraint_count
                            if flow.passenger_solution is not None
                            else 0
                        ),
                        master_served_passenger_count=(
                            flow.passenger_solution.served_passenger_count
                            if flow.passenger_solution is not None
                            else None
                        ),
                        master_unserved_passenger_count=(
                            flow.passenger_solution.unserved_passenger_count
                            if flow.passenger_solution is not None
                            else None
                        ),
                        resource_window_resolve_count=(
                            resource_window_resolve_count
                        ),
                        resource_window_candidate_count=(
                            resource_window_candidate_count
                        ),
                        resource_window_violated_count=(
                            resource_window_violated_count
                        ),
                        resource_window_duplicate_count=(
                            resource_window_duplicate_count
                        ),
                        resource_window_added_count=len(round_resource_window_rows),
                        resource_window_entry_row_count=(
                            resource_window_entry_row_count
                        ),
                        resource_window_energy_row_count=(
                            resource_window_energy_row_count
                        ),
                        resource_window_separation_seconds=(
                            resource_window_separation_seconds
                        ),
                        resource_window_master_seconds=(
                            resource_window_master_seconds
                        ),
                        resource_window_lower_bound_before=(
                            resource_window_lower_bound_before
                        ),
                        resource_window_lower_bound_after=(
                            resource_window_lower_bound_after
                        ),
                        **_master_diagnostic_kwargs(flow),
                    )
                )
                continue

            recovery_started = perf_counter()
            recovered_schedules: list[DddRecoveredSchedule] = []
            recovery_feasible = True
            for path_problem, path in zip(path_problems, paths, strict=True):
                recovered = recovery.recover(path_problem, path)
                if (
                    recovered.status is not DddPrimalRecoveryStatus.FEASIBLE
                    or recovered.schedule is None
                ):
                    recovery_feasible = False
                    break
                recovered_schedules.append(recovered.schedule)
            recovery_objective: float | None = None
            recovery_validation = _not_run_validation()
            if recovery_feasible:
                recovery_validation = _validate_reference_solution(
                    current,
                    tuple(recovered_schedules),
                    tolerance_seconds=self.tolerance_seconds,
                )
                if recovery_validation.solution is None:
                    recovery_feasible = False
                else:
                    recovery_objective = sum(
                        schedule.objective_value for schedule in recovered_schedules
                    )
                    consider_primal_candidate(
                        tuple(recovered_schedules),
                        recovery_validation.solution,
                    )
            recovery_seconds = perf_counter() - recovery_started
            emit(
                DddNetworkTimeRefinementProgressStage.RECOVERY_FINISHED,
                round_index,
            )

            lifting_started = perf_counter()
            cell_lift_statuses: list[DddStrictTimeLiftStatus] = []
            cell_lift_schedules: list[DddRecoveredSchedule] = []
            inconsistencies: list[DddEventCellInconsistency] = []
            refinement_stalled_detail: str | None = None
            for path_problem, path in zip(path_problems, paths, strict=True):
                try:
                    cell_lift = cell_lifter.lift(path_problem, path)
                except DddTimeRefinementStalledError as error:
                    if refinement_stalled_detail is None:
                        refinement_stalled_detail = str(error)
                    continue
                cell_lift_statuses.append(cell_lift.status)
                if cell_lift.schedule is not None:
                    cell_lift_schedules.append(cell_lift.schedule)
                inconsistencies.extend(cell_lift.inconsistencies)
            time_splits, refined_discretization = _build_time_split_batch(
                current.discretization,
                tuple(inconsistencies),
                max_splits=self.max_new_time_splits_per_iteration,
                tolerance_seconds=self.tolerance_seconds,
            )
            trajectory_time_split_count = len(time_splits)
            resource_time_split_count = 0
            cell_lift_validation = _not_run_validation()
            if refinement_stalled_detail is not None:
                cell_lift_validation = DddNetworkValidationResult(
                    status=DddNetworkValidationStatus.INVALID,
                    solution=None,
                    detail=refinement_stalled_detail,
                    conflicts=(),
                    cuts=(),
                )
            elif len(cell_lift_schedules) == len(paths):
                cell_lift_validation = _validate_reference_solution(
                    current,
                    tuple(cell_lift_schedules),
                    tolerance_seconds=self.tolerance_seconds,
                )
                if cell_lift_validation.solution is not None:
                    consider_primal_candidate(
                        tuple(cell_lift_schedules),
                        cell_lift_validation.solution,
                    )

            resource_row_proofs = (
                _build_universal_resource_rows_for_conflicts(
                    network,
                    paths,
                    cell_lift_validation.conflicts,
                )
                if self.use_universal_resource_rows
                else ()
            )
            active_resource_row_ids = {row.id for row in active_resource_rows}
            selected_resource_row_proofs = tuple(
                proof
                for proof in resource_row_proofs
                if proof[0].id not in active_resource_row_ids
            )[: self.max_new_cuts_per_iteration]
            universal_resource_rows = tuple(
                row for row, _ in selected_resource_row_proofs
            )
            covered_conflict_indices = {
                conflict_index
                for _, conflict_indices in selected_resource_row_proofs
                for conflict_index in conflict_indices
            }
            uncovered_conflicts = tuple(
                conflict
                for conflict_index, conflict in enumerate(
                    cell_lift_validation.conflicts
                )
                if conflict_index not in covered_conflict_indices
            )
            resource_conflict_splits = _build_resource_conflict_splits(
                network,
                paths,
                uncovered_conflicts,
                cell_lift_validation.support_selection,
            )
            if resource_conflict_splits:
                remaining_split_budget = max(
                    0,
                    self.max_new_time_splits_per_iteration - len(time_splits),
                )
                selected_resource_splits = resource_conflict_splits[
                    :remaining_split_budget
                ]
                for split in selected_resource_splits:
                    refined_discretization = refined_discretization.split(
                        state_id=split.state_id,
                        boundary_seconds=split.boundary_seconds,
                        tolerance_seconds=self.tolerance_seconds,
                    )
                time_splits = (*time_splits, *selected_resource_splits)
                resource_time_split_count = len(selected_resource_splits)

            new_resource_rows = tuple(
                row
                for row in universal_resource_rows
                if row.id not in active_resource_row_ids
            )[: self.max_new_cuts_per_iteration]

            if uncovered_conflicts and not resource_conflict_splits:
                if cell_lift_validation.support_selection is None:
                    return _result(
                        status=DddNetworkTimeRefinementStatus.INVALID_INTERNAL,
                        schedules=best_schedules,
                        reference_solution=best_reference,
                        lower_bound=lower_bound,
                        upper_bound=upper_bound,
                        iterations=iterations,
                        discretization=current.discretization,
                        cuts=cuts,
                        primal_evaluation=best_primal_evaluation,
                        aggregate_support_cuts=aggregate_support_cuts,
                        aggregate_distance_cuts=aggregate_distance_cuts,
                        timed_flow_cover_cuts=timed_flow_cover_cuts,
                        bootstrap_result=bootstrap_result,
                        bootstrap_objective=bootstrap_objective,
                    )
                candidate_cuts = (
                    cell_lift_validation.cuts
                    if len(uncovered_conflicts) == len(cell_lift_validation.conflicts)
                    else build_ddd_prefix_conflict_cuts(
                        cell_lift_validation.support_selection,
                        uncovered_conflicts,
                    )
                )
            else:
                candidate_cuts = ()
            new_cuts, prefix_budget_exhausted = _select_prefix_cuts_within_budget(
                network,
                tuple(cuts),
                tuple(cut for cut in candidate_cuts if cut.id not in cut_ids),
                max_new_cuts=self.max_new_cuts_per_iteration,
                max_variable_count=self.max_prefix_variable_count,
                max_cabin_count=self.max_tracked_prefix_cabin_count,
                max_visit_index=self.max_prefix_visit_index,
            )
            if (
                cell_lift_validation.status
                is DddNetworkValidationStatus.RESOURCE_CONFLICT
                and not _has_resource_conflict_refinement(
                    time_splits=time_splits,
                    new_cuts=new_cuts,
                    new_resource_rows=new_resource_rows,
                )
                and not new_aggregate_support_cuts
            ):
                return _result(
                    status=(
                        DddNetworkTimeRefinementStatus.REFINEMENT_BUDGET_EXHAUSTED
                        if prefix_budget_exhausted
                        else DddNetworkTimeRefinementStatus.INVALID_INTERNAL
                    ),
                    schedules=best_schedules,
                    reference_solution=best_reference,
                    lower_bound=lower_bound,
                    upper_bound=upper_bound,
                    iterations=iterations,
                    discretization=current.discretization,
                    cuts=cuts,
                    primal_evaluation=best_primal_evaluation,
                    aggregate_support_cuts=aggregate_support_cuts,
                    aggregate_distance_cuts=aggregate_distance_cuts,
                    timed_flow_cover_cuts=timed_flow_cover_cuts,
                    bootstrap_result=bootstrap_result,
                    bootstrap_objective=bootstrap_objective,
                )
            cuts.extend(new_cuts)
            cut_ids.update(cut.id for cut in new_cuts)
            active_resource_rows.extend(new_resource_rows)
            universal_resource_row_ids.update(
                row.id
                for row in new_resource_rows
                if row.kind is DddAnonymousResourceRowKind.UNIVERSAL_CONFLICT
            )
            interval_resource_row_ids.update(
                row.id
                for row in new_resource_rows
                if row.kind
                in (
                    DddAnonymousResourceRowKind.INTERVAL_CAPACITY,
                    DddAnonymousResourceRowKind.INTERVAL_ENERGY,
                )
            )
            lifting_and_validation_seconds = perf_counter() - lifting_started
            emit(
                DddNetworkTimeRefinementProgressStage.LIFTING_FINISHED,
                round_index,
            )
            if (
                self.use_trajectory_slot_pool
                and primal_evaluator is not None
                and len(trajectory_pool_candidates) >= 2
            ):
                emit(
                    DddNetworkTimeRefinementProgressStage.TRAJECTORY_POOL_STARTED,
                    round_index,
                )
                pool_evaluation: DddPrimalPoolEvaluationResult = (
                    primal_evaluator.evaluate_trajectory_pool(
                        current,
                        tuple(trajectory_pool_candidates),
                    )
                )
                trajectory_pool_result = pool_evaluation.pool_result
                evaluation = pool_evaluation.evaluation
                if evaluation is not None:
                    primal_candidate_summaries.append(evaluation.summary)
                    primal_evaluation_count += 1
                    primal_evaluation_seconds += evaluation.total_seconds
                    if (
                        evaluation.status is DddPrimalEvaluationStatus.FEASIBLE
                        and evaluation.objective_value is not None
                        and trajectory_pool_result.reference_solution is not None
                    ):
                        primal_evaluation_status = DddPrimalEvaluationStatus.FEASIBLE
                        if (
                            round_primal_objective is None
                            or evaluation.objective_value < round_primal_objective
                        ):
                            round_primal_objective = evaluation.objective_value
                            round_primal_evaluation = evaluation
                        if evaluation.objective_value < upper_bound:
                            upper_bound = evaluation.objective_value
                            best_schedules = trajectory_pool_result.schedules
                            best_reference = trajectory_pool_result.reference_solution
                            best_primal_evaluation = evaluation
                emit(
                    DddNetworkTimeRefinementProgressStage.TRAJECTORY_POOL_FINISHED,
                    round_index,
                )
            record_iteration(
                _iteration(
                    round_index=round_index,
                    problem=current,
                    node_count=len(network.nodes),
                    arc_count=len(network.arcs),
                    variable_count=flow.variable_count,
                    constraint_count=flow.constraint_count,
                    prefix_variable_count=flow.prefix_variable_count,
                    conflict_constraint_count=flow.conflict_constraint_count,
                    resource_constraint_count=flow.resource_constraint_count,
                    mandatory_resource_constraint_count=(
                        flow.mandatory_resource_constraint_count
                    ),
                    additional_resource_constraint_count=(
                        flow.additional_resource_constraint_count
                    ),
                    added_resource_row_ids=tuple(
                        row.id
                        for row in (*round_resource_window_rows, *new_resource_rows)
                    ),
                    total_universal_resource_row_count=len(universal_resource_row_ids),
                    total_interval_resource_row_count=len(interval_resource_row_ids),
                    tracked_prefix_cabin_count=(flow.tracked_prefix_cabin_count),
                    warm_start_arc_variable_count=(flow.warm_start_arc_variable_count),
                    warm_start_prefix_variable_count=(
                        flow.warm_start_prefix_variable_count
                    ),
                    warm_start_projected_cabin_count=(
                        flow.warm_start_projected_cabin_count
                    ),
                    warm_start_complete_cabin_count=(
                        flow.warm_start_complete_cabin_count
                    ),
                    path_count=len(paths),
                    master_bound=flow.best_bound,
                    lower_bound=lower_bound,
                    recovery_feasible=recovery_feasible,
                    recovery_objective=recovery_objective,
                    recovery_validation_status=recovery_validation.status,
                    upper_bound=upper_bound,
                    cell_lift_statuses=tuple(cell_lift_statuses),
                    cell_lift_validation=cell_lift_validation,
                    conflict_count=len(cell_lift_validation.conflicts),
                    added_cut_ids=tuple(cut.id for cut in new_cuts),
                    total_conflict_cut_count=len(cuts),
                    time_splits=time_splits,
                    trajectory_time_split_count=trajectory_time_split_count,
                    resource_time_split_count=resource_time_split_count,
                    cuts=active_cuts,
                    network_partition_cache_hits=(
                        builder.last_build_stats.partition_cache_hits
                    ),
                    network_partition_cache_misses=(
                        builder.last_build_stats.partition_cache_misses
                    ),
                    network_transition_cache_hits=(
                        builder.last_build_stats.transition_cache_hits
                    ),
                    network_transition_cache_misses=(
                        builder.last_build_stats.transition_cache_misses
                    ),
                    network_invalidated_state_count=(
                        builder.last_build_stats.invalidated_state_count
                    ),
                    network_build_seconds=network_build_seconds,
                    master_solve_seconds=master_solve_seconds,
                    decomposition_seconds=decomposition_seconds,
                    recovery_seconds=recovery_seconds,
                    lifting_and_validation_seconds=(lifting_and_validation_seconds),
                    round_seconds=perf_counter() - round_started,
                    cp_sat_status=cp_sat_status,
                    cp_sat_seconds=cp_sat_seconds,
                    cp_sat_conflict_count=cp_sat_conflict_count,
                    cp_sat_branch_count=cp_sat_branch_count,
                    cp_sat_candidate_count=cp_sat_candidate_count,
                    cp_sat_search_complete=cp_sat_search_complete,
                    cp_sat_cabin_path_status=cp_sat_cabin_path_status,
                    cp_sat_cabin_path_seconds=cp_sat_cabin_path_seconds,
                    cp_sat_cabin_path_core_cabin_ids=(
                        cp_sat_cabin_path_core_cabin_ids
                    ),
                    cp_sat_cabin_path_core_literal_count=(
                        cp_sat_cabin_path_core_literal_count
                    ),
                    cp_sat_cabin_path_cut_literal_count=(
                        cp_sat_cabin_path_cut_literal_count
                    ),
                    added_cabin_path_core_cut_ids=tuple(
                        cut.id
                        for cut in new_cuts
                        if cut.provenance
                        == "exact_cp_sat_no_wait_cabin_path_core"
                    ),
                    primal_evaluation_status=primal_evaluation_status,
                    primal_evaluation_count=primal_evaluation_count,
                    primal_evaluation_seconds=primal_evaluation_seconds,
                    primal_objective_value=round_primal_objective,
                    served_passenger_count=(
                        round_primal_evaluation.served_passenger_count
                        if round_primal_evaluation is not None
                        else None
                    ),
                    unserved_passenger_count=(
                        round_primal_evaluation.unserved_passenger_count
                        if round_primal_evaluation is not None
                        else None
                    ),
                    primal_candidate_summaries=tuple(primal_candidate_summaries),
                    trajectory_pool_result=trajectory_pool_result,
                    aggregate_support_constraint_count=(
                        flow.aggregate_support_constraint_count
                    ),
                    aggregate_threshold_variable_count=(
                        flow.aggregate_threshold_variable_count
                    ),
                    timed_flow_cover_constraint_count=(
                        flow.timed_flow_cover_constraint_count
                    ),
                    timed_flow_threshold_variable_count=(
                        flow.timed_flow_threshold_variable_count
                    ),
                    fixed_start_structural_constraint_count=(
                        flow.fixed_start_structural_constraint_count
                    ),
                    added_aggregate_support_cut_ids=tuple(
                        cut.id for cut in new_aggregate_support_cuts
                    ),
                    cp_sat_core_literal_count=cp_sat_core_literal_count,
                    cp_sat_timed_flow_core_literal_count=(
                        cp_sat_timed_flow_core_literal_count
                    ),
                    cp_sat_timed_flow_core_resource_ids=(
                        cp_sat_timed_flow_core_resource_ids
                    ),
                    cp_sat_local_explainability=cp_sat_local_explainability,
                    added_timed_flow_cover_cut_ids=tuple(
                        cut.id for cut in new_timed_flow_cover_cuts
                    ),
                    master_passenger_variable_count=(
                        flow.passenger_solution.variable_count
                        if flow.passenger_solution is not None
                        else 0
                    ),
                    master_passenger_constraint_count=(
                        flow.passenger_solution.constraint_count
                        if flow.passenger_solution is not None
                        else 0
                    ),
                    master_served_passenger_count=(
                        flow.passenger_solution.served_passenger_count
                        if flow.passenger_solution is not None
                        else None
                    ),
                    master_unserved_passenger_count=(
                        flow.passenger_solution.unserved_passenger_count
                        if flow.passenger_solution is not None
                        else None
                    ),
                    resource_window_resolve_count=resource_window_resolve_count,
                    resource_window_candidate_count=(
                        resource_window_candidate_count
                    ),
                    resource_window_violated_count=(
                        resource_window_violated_count
                    ),
                    resource_window_duplicate_count=(
                        resource_window_duplicate_count
                    ),
                    resource_window_added_count=len(round_resource_window_rows),
                    resource_window_entry_row_count=(
                        resource_window_entry_row_count
                    ),
                    resource_window_energy_row_count=(
                        resource_window_energy_row_count
                    ),
                    resource_window_separation_seconds=(
                        resource_window_separation_seconds
                    ),
                    resource_window_master_seconds=resource_window_master_seconds,
                    resource_window_lower_bound_before=(
                        resource_window_lower_bound_before
                    ),
                    resource_window_lower_bound_after=(
                        resource_window_lower_bound_after
                    ),
                    **_master_diagnostic_kwargs(flow),
                )
            )
            if cp_sat_exact_infeasible:
                return _result(
                    status=(
                        DddNetworkTimeRefinementStatus.INVALID_INTERNAL
                        if best_reference is not None
                        else DddNetworkTimeRefinementStatus.EXACT_INFEASIBLE
                    ),
                    schedules=best_schedules,
                    reference_solution=best_reference,
                    lower_bound=lower_bound,
                    upper_bound=(
                        upper_bound if best_reference is not None else math.inf
                    ),
                    iterations=iterations,
                    discretization=current.discretization,
                    cuts=cuts,
                    primal_evaluation=None,
                    aggregate_support_cuts=aggregate_support_cuts,
                    aggregate_distance_cuts=aggregate_distance_cuts,
                    timed_flow_cover_cuts=timed_flow_cover_cuts,
                    bootstrap_result=bootstrap_result,
                    bootstrap_objective=bootstrap_objective,
                )
            if (
                refinement_stalled_detail is not None
                and not time_splits
                and not new_cuts
                and not new_resource_rows
                and not new_aggregate_support_cuts
            ):
                return _result(
                    status=DddNetworkTimeRefinementStatus.REFINEMENT_STALLED,
                    schedules=best_schedules,
                    reference_solution=best_reference,
                    lower_bound=lower_bound,
                    upper_bound=upper_bound,
                    iterations=iterations,
                    discretization=current.discretization,
                    cuts=cuts,
                    primal_evaluation=best_primal_evaluation,
                    aggregate_support_cuts=aggregate_support_cuts,
                    aggregate_distance_cuts=aggregate_distance_cuts,
                    timed_flow_cover_cuts=timed_flow_cover_cuts,
                    bootstrap_result=bootstrap_result,
                    bootstrap_objective=bootstrap_objective,
                )
            if lower_bound > upper_bound + self.bound_tolerance:
                return _result(
                    status=DddNetworkTimeRefinementStatus.INVALID_INTERNAL,
                    schedules=best_schedules,
                    reference_solution=best_reference,
                    lower_bound=lower_bound,
                    upper_bound=upper_bound,
                    iterations=iterations,
                    discretization=current.discretization,
                    cuts=cuts,
                    primal_evaluation=best_primal_evaluation,
                    aggregate_support_cuts=aggregate_support_cuts,
                    aggregate_distance_cuts=aggregate_distance_cuts,
                    timed_flow_cover_cuts=timed_flow_cover_cuts,
                    bootstrap_result=bootstrap_result,
                    bootstrap_objective=bootstrap_objective,
                )
            if upper_bound - lower_bound <= self.bound_tolerance:
                return _result(
                    status=DddNetworkTimeRefinementStatus.OPTIMAL,
                    schedules=best_schedules,
                    reference_solution=best_reference,
                    lower_bound=lower_bound,
                    upper_bound=upper_bound,
                    iterations=iterations,
                    discretization=current.discretization,
                    cuts=cuts,
                    primal_evaluation=best_primal_evaluation,
                    aggregate_support_cuts=aggregate_support_cuts,
                    aggregate_distance_cuts=aggregate_distance_cuts,
                    timed_flow_cover_cuts=timed_flow_cover_cuts,
                    bootstrap_result=bootstrap_result,
                    bootstrap_objective=bootstrap_objective,
                )
            if (
                not time_splits
                and not new_cuts
                and not new_resource_rows
                and not new_aggregate_support_cuts
            ):
                return _result(
                    status=(
                        DddNetworkTimeRefinementStatus.FEASIBLE_WITH_GAP
                        if best_reference is not None
                        else DddNetworkTimeRefinementStatus.UNKNOWN_NO_INCUMBENT
                    ),
                    schedules=best_schedules,
                    reference_solution=best_reference,
                    lower_bound=lower_bound,
                    upper_bound=upper_bound,
                    iterations=iterations,
                    discretization=current.discretization,
                    cuts=cuts,
                    primal_evaluation=best_primal_evaluation,
                    aggregate_support_cuts=aggregate_support_cuts,
                    aggregate_distance_cuts=aggregate_distance_cuts,
                    timed_flow_cover_cuts=timed_flow_cover_cuts,
                    bootstrap_result=bootstrap_result,
                    bootstrap_objective=bootstrap_objective,
                )
            if time_splits:
                current = current.with_discretization(refined_discretization)

        return _result(
            status=(
                DddNetworkTimeRefinementStatus.FEASIBLE_WITH_GAP
                if best_reference is not None
                else DddNetworkTimeRefinementStatus.UNKNOWN_NO_INCUMBENT
            ),
            schedules=best_schedules,
            reference_solution=best_reference,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            iterations=iterations,
            discretization=current.discretization,
            cuts=cuts,
            primal_evaluation=best_primal_evaluation,
            aggregate_support_cuts=aggregate_support_cuts,
            aggregate_distance_cuts=aggregate_distance_cuts,
            timed_flow_cover_cuts=timed_flow_cover_cuts,
            bootstrap_result=bootstrap_result,
            bootstrap_objective=bootstrap_objective,
        )


def _build_universal_resource_rows_for_conflicts(
    network: DddLayeredTimeNetwork,
    paths: tuple[DddPartialTimedPath, ...],
    conflicts: tuple[DddReferenceConflict, ...],
) -> tuple[tuple[DddAnonymousResourceRow, tuple[int, ...]], ...]:
    """Classify exact conflicts that are universal in their current cells."""

    if not conflicts:
        return ()
    selected_arc_by_visit = _selected_arc_by_visit(network, paths)

    proof_by_row_id: dict[str, tuple[DddAnonymousResourceRow, set[int]]] = {}
    for conflict_index, conflict in enumerate(conflicts):
        first_arc = selected_arc_by_visit.get(
            (conflict.first_cabin_id, conflict.first_visit_index)
        )
        second_arc = selected_arc_by_visit.get(
            (conflict.second_cabin_id, conflict.second_visit_index)
        )
        if first_arc is None or second_arc is None:
            raise RuntimeError("DDD resource conflict references an unselected visit")
        first_windows = tuple(
            window
            for window in first_arc.resource_windows
            if window.resource_id == conflict.resource_id
        )
        second_windows = tuple(
            window
            for window in second_arc.resource_windows
            if window.resource_id == conflict.resource_id
        )
        for first_window in first_windows:
            for second_window in second_windows:
                row = build_ddd_universal_resource_row(
                    first_window,
                    second_window,
                )
                if row is None:
                    continue
                existing = proof_by_row_id.get(row.id)
                if existing is None:
                    proof_by_row_id[row.id] = (row, {conflict_index})
                else:
                    existing[1].add(conflict_index)

    return tuple(
        (row, tuple(sorted(conflict_indices)))
        for row, conflict_indices in proof_by_row_id.values()
    )


def _selected_arc_by_visit(
    network: DddLayeredTimeNetwork,
    paths: tuple[DddPartialTimedPath, ...],
) -> dict[tuple[int, int], DddLayeredTimeArc]:
    selected_arc_by_visit: dict[tuple[int, int], DddLayeredTimeArc] = {}
    for path in paths:
        for partial_arc in path.arcs:
            candidates = tuple(
                arc
                for arc in network.arcs
                if arc.partial_arc == partial_arc
                and (
                    (
                        partial_arc.visit_index == 0
                        and arc.kind is DddLayeredTimeArcKind.SOURCE
                        and arc.cabin_id == path.cabin_id
                    )
                    or (
                        partial_arc.visit_index > 0
                        and arc.kind is DddLayeredTimeArcKind.MOVEMENT
                    )
                )
            )
            if len(candidates) != 1:
                raise RuntimeError(
                    "DDD selected partial visit does not identify one layered arc"
                )
            selected_arc_by_visit[(path.cabin_id, partial_arc.visit_index)] = (
                candidates[0]
            )
    return selected_arc_by_visit


def _build_resource_conflict_splits(
    network: DddLayeredTimeNetwork,
    paths: tuple[DddPartialTimedPath, ...],
    conflicts: tuple[DddReferenceConflict, ...],
    selection: DddSupportSelection | None,
) -> tuple[DddTimeSplit, ...]:
    """Split current source cells at exact headway-order thresholds."""

    if not conflicts or selection is None:
        return ()
    selected_arc_by_visit = _selected_arc_by_visit(network, paths)
    visit_by_key = {
        (trajectory.cabin_id, visit.visit_index): visit
        for trajectory in selection.trajectories
        for visit in trajectory.visits
    }
    splits: set[DddTimeSplit] = set()
    for conflict in conflicts:
        first_arc = selected_arc_by_visit.get(
            (conflict.first_cabin_id, conflict.first_visit_index)
        )
        second_arc = selected_arc_by_visit.get(
            (conflict.second_cabin_id, conflict.second_visit_index)
        )
        if first_arc is None or second_arc is None:
            raise RuntimeError("DDD resource conflict references an unselected visit")
        first_visit = visit_by_key[
            (conflict.first_cabin_id, conflict.first_visit_index)
        ]
        second_visit = visit_by_key[
            (conflict.second_cabin_id, conflict.second_visit_index)
        ]
        first_source_tick = ddd_seconds_to_tick(first_visit.switch_time_seconds)
        second_source_tick = ddd_seconds_to_tick(second_visit.switch_time_seconds)
        first_windows = tuple(
            window
            for window in first_arc.resource_windows
            if window.resource_id == conflict.resource_id
        )
        second_windows = tuple(
            window
            for window in second_arc.resource_windows
            if window.resource_id == conflict.resource_id
        )
        for first_window in first_windows:
            for second_window in second_windows:
                second_boundary_tick = (
                    first_source_tick
                    + first_window.leader_clear_offset_tick
                    + first_window.headway_tick
                    - second_window.follower_enter_offset_tick
                )
                first_boundary_tick = (
                    second_source_tick
                    + second_window.leader_clear_offset_tick
                    + second_window.headway_tick
                    - first_window.follower_enter_offset_tick
                )
                for arc, window, boundary_tick in (
                    (second_arc, second_window, second_boundary_tick),
                    (first_arc, first_window, first_boundary_tick),
                ):
                    if (
                        arc.kind is not DddLayeredTimeArcKind.MOVEMENT
                        or arc.partial_arc is None
                        or not (
                            window.source_interval.lower_tick
                            < boundary_tick
                            < window.source_interval.upper_tick
                        )
                    ):
                        continue
                    splits.add(
                        DddTimeSplit(
                            state_id=arc.partial_arc.from_state_id,
                            boundary_seconds=ddd_tick_to_seconds(boundary_tick),
                        )
                    )
    return tuple(sorted(splits))


def _validate_reference_solution(
    problem: DddNetworkTimeProblem,
    schedules: tuple[DddRecoveredSchedule, ...],
    *,
    tolerance_seconds: float,
) -> DddNetworkValidationResult:
    starts_by_cabin = {
        start.cabin_id: start for start in problem.movement_problem.starts
    }
    options_by_id = {
        option.id: option for option in problem.movement_problem.route_options
    }
    trajectories: list[DddReferenceTrajectory] = []
    try:
        for schedule in sorted(schedules, key=lambda item: item.cabin_id):
            start = starts_by_cabin[schedule.cabin_id]
            visits = tuple(
                build_ddd_reference_visit(
                    start=start,
                    visit_index=visit_index,
                    switch_time_seconds=schedule.events[visit_index].time_seconds,
                    option=options_by_id[option_id],
                    operational_end_seconds=(
                        problem.movement_problem.operational_end_seconds
                    ),
                    tolerance_seconds=tolerance_seconds,
                )
                for visit_index, option_id in enumerate(schedule.route_option_ids)
            )
            trajectories.append(
                DddReferenceTrajectory(
                    cabin_id=schedule.cabin_id,
                    visits=visits,
                )
            )
        solution = DddReferenceSolution(tuple(trajectories))
        validate_ddd_reference_solution(
            problem.movement_problem,
            solution,
            tolerance_seconds=tolerance_seconds,
        )
    except KeyError as error:
        return DddNetworkValidationResult(
            status=DddNetworkValidationStatus.INVALID,
            solution=None,
            detail=str(error),
            conflicts=(),
            cuts=(),
        )
    except DddReferenceHorizonCoverageError as error:
        return DddNetworkValidationResult(
            status=DddNetworkValidationStatus.HORIZON_INCOMPLETE,
            solution=None,
            detail=str(error),
            conflicts=(),
            cuts=(),
        )
    except DddReferenceResourceConflictError as error:
        conflicts = find_ddd_reference_conflicts(
            tuple(
                occurrence
                for trajectory in trajectories
                for occurrence in trajectory.resource_occurrences
            ),
            problem.movement_problem,
            tolerance_seconds=tolerance_seconds,
        )
        selection = DddSupportSelection(tuple(trajectories))
        return DddNetworkValidationResult(
            status=DddNetworkValidationStatus.RESOURCE_CONFLICT,
            solution=None,
            detail=str(error),
            conflicts=conflicts,
            cuts=build_ddd_prefix_conflict_cuts(selection, conflicts),
            support_selection=selection,
        )
    except ValueError as error:
        return DddNetworkValidationResult(
            status=DddNetworkValidationStatus.INVALID,
            solution=None,
            detail=str(error),
            conflicts=(),
            cuts=(),
        )
    return DddNetworkValidationResult(
        status=DddNetworkValidationStatus.FEASIBLE,
        solution=solution,
        detail=None,
        conflicts=(),
        cuts=(),
    )


def _not_run_validation() -> DddNetworkValidationResult:
    return DddNetworkValidationResult(
        status=DddNetworkValidationStatus.NOT_RUN,
        solution=None,
        detail=None,
        conflicts=(),
        cuts=(),
    )


def _has_resource_conflict_refinement(
    *,
    time_splits: tuple[DddTimeSplit, ...],
    new_cuts: tuple[DddSupportConflictCut, ...],
    new_resource_rows: tuple[DddAnonymousResourceRow, ...],
) -> bool:
    """Return whether a resource conflict has any safe next refinement."""

    return bool(time_splits or new_cuts or new_resource_rows)


def _build_time_split_batch(
    discretization: DddTimeDiscretization,
    inconsistencies: tuple[DddEventCellInconsistency, ...],
    *,
    max_splits: int,
    tolerance_seconds: float,
) -> tuple[tuple[DddTimeSplit, ...], DddTimeDiscretization]:
    """Apply a deterministic batch of tolerance-safe partition refinements."""
    selected: list[DddTimeSplit] = []
    refined = discretization
    for inconsistency in sorted(
        inconsistencies,
        key=lambda item: (
            item.state_id,
            item.split_boundary_seconds,
            item.selected_cell_id,
            item.exact_source_time_seconds,
            item.failed_target_cell_id,
        ),
    ):
        split = DddTimeSplit(
            state_id=inconsistency.state_id,
            boundary_seconds=inconsistency.split_boundary_seconds,
        )
        if any(
            existing.state_id == split.state_id
            and ddd_seconds_to_tick(existing.boundary_seconds)
            == ddd_seconds_to_tick(split.boundary_seconds)
            for existing in selected
        ):
            continue
        refined = refined.split(
            state_id=split.state_id,
            boundary_seconds=split.boundary_seconds,
            tolerance_seconds=tolerance_seconds,
        )
        selected.append(split)
        if len(selected) >= max_splits:
            break
    return tuple(selected), refined


def _prefix_depths(
    cuts: tuple[DddSupportConflictCut, ...],
) -> dict[int, int]:
    depths: dict[int, int] = {}
    for cut in cuts:
        for literal in cut.literals:
            depths[literal.cabin_id] = max(
                depths.get(literal.cabin_id, 0),
                literal.visit_index,
            )
    return depths


def _prefix_formulation_within_budget(
    network: DddLayeredTimeNetwork,
    cuts: tuple[DddSupportConflictCut, ...],
    *,
    max_variable_count: int,
    max_cabin_count: int,
    max_visit_index: int,
) -> bool:
    depths = _prefix_depths(cuts)
    if len(tuple(value for value in depths.values() if value > 0)) > max_cabin_count:
        return False
    if max(depths.values(), default=0) > max_visit_index:
        return False
    size = estimate_ddd_prefix_formulation_size(
        network,
        max_visit_index_by_cabin=depths,
    )
    return size.prefix_variable_count <= max_variable_count


def _select_prefix_cuts_within_budget(
    network: DddLayeredTimeNetwork,
    existing: tuple[DddSupportConflictCut, ...],
    candidates: tuple[DddSupportConflictCut, ...],
    *,
    max_new_cuts: int,
    max_variable_count: int,
    max_cabin_count: int,
    max_visit_index: int,
) -> tuple[tuple[DddSupportConflictCut, ...], bool]:
    selected: list[DddSupportConflictCut] = []
    budget_exhausted = False
    for candidate in candidates:
        if len(selected) >= max_new_cuts:
            break
        trial = (*existing, *selected, candidate)
        if not _prefix_formulation_within_budget(
            network,
            trial,
            max_variable_count=max_variable_count,
            max_cabin_count=max_cabin_count,
            max_visit_index=max_visit_index,
        ):
            budget_exhausted = True
            continue
        selected.append(candidate)
    return tuple(selected), budget_exhausted


def _master_diagnostic_kwargs(flow: DddAnonymousFlowResult) -> dict[str, object]:
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


def _iteration(
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
    cp_sat_cabin_path_status: DddCpSatPrimalStatus = (
        DddCpSatPrimalStatus.NOT_RUN
    ),
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
        cp_sat_status=cp_sat_status,
        cp_sat_seconds=cp_sat_seconds,
        cp_sat_conflict_count=cp_sat_conflict_count,
        cp_sat_branch_count=cp_sat_branch_count,
        cp_sat_candidate_count=cp_sat_candidate_count,
        cp_sat_search_complete=cp_sat_search_complete,
        cp_sat_cabin_path_status=cp_sat_cabin_path_status,
        cp_sat_cabin_path_seconds=cp_sat_cabin_path_seconds,
        cp_sat_cabin_path_core_cabin_ids=cp_sat_cabin_path_core_cabin_ids,
        cp_sat_cabin_path_core_literal_count=(
            cp_sat_cabin_path_core_literal_count
        ),
        cp_sat_cabin_path_cut_literal_count=(
            cp_sat_cabin_path_cut_literal_count
        ),
        added_cabin_path_core_cut_ids=added_cabin_path_core_cut_ids,
        primal_evaluation_status=primal_evaluation_status,
        primal_evaluation_count=primal_evaluation_count,
        primal_evaluation_seconds=primal_evaluation_seconds,
        primal_objective_value=primal_objective_value,
        served_passenger_count=served_passenger_count,
        unserved_passenger_count=unserved_passenger_count,
        primal_candidate_summaries=primal_candidate_summaries,
        trajectory_pool_status=(
            trajectory_pool_result.status
            if trajectory_pool_result is not None
            else None
        ),
        trajectory_pool_option_count=(
            trajectory_pool_result.trajectory_option_count
            if trajectory_pool_result is not None
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
            if trajectory_pool_result is not None
            else 0.0
        ),
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


def _result(
    *,
    status: DddNetworkTimeRefinementStatus,
    schedules: tuple[DddRecoveredSchedule, ...],
    reference_solution: DddReferenceSolution | None,
    lower_bound: float,
    upper_bound: float,
    iterations: list[DddNetworkTimeRefinementIteration],
    discretization: DddTimeDiscretization,
    cuts: list[DddSupportConflictCut],
    primal_evaluation: DddPrimalEvaluationResult | None = None,
    aggregate_support_cuts: list[DddAggregateSupportCut] | None = None,
    aggregate_distance_cuts: list[DddAggregateSupportDistanceCut] | None = None,
    timed_flow_cover_cuts: list[DddTimedFlowCoverCut] | None = None,
    bootstrap_result: DddCpSatPrimalResult | None = None,
    bootstrap_objective: float | None = None,
) -> DddNetworkTimeRefinementResult:
    finite_lower = _finite_or_none(lower_bound)
    finite_upper = _finite_or_none(upper_bound)
    gap = (
        max(0.0, finite_upper - finite_lower)
        if finite_lower is not None and finite_upper is not None
        else None
    )
    return DddNetworkTimeRefinementResult(
        status=status,
        schedules=schedules,
        reference_solution=reference_solution,
        global_lower_bound=finite_lower,
        global_upper_bound=finite_upper,
        absolute_gap=gap,
        iterations=tuple(iterations),
        final_discretization=discretization,
        conflict_cuts=tuple(cuts),
        primal_evaluation=primal_evaluation,
        aggregate_support_cuts=tuple(aggregate_support_cuts or ()),
        aggregate_distance_cuts=tuple(aggregate_distance_cuts or ()),
        timed_flow_cover_cuts=tuple(timed_flow_cover_cuts or ()),
        cp_sat_bootstrap_status=(
            bootstrap_result.status
            if isinstance(bootstrap_result, DddCpSatPrimalResult)
            else DddCpSatPrimalStatus.NOT_RUN
        ),
        cp_sat_bootstrap_seconds=(
            bootstrap_result.wall_seconds
            if isinstance(bootstrap_result, DddCpSatPrimalResult)
            else 0.0
        ),
        cp_sat_bootstrap_candidate_count=(
            len(bootstrap_result.candidate_schedules)
            if isinstance(bootstrap_result, DddCpSatPrimalResult)
            else 0
        ),
        cp_sat_bootstrap_objective=bootstrap_objective,
    )


def _finite_or_none(value: float) -> float | None:
    return value if math.isfinite(value) else None
