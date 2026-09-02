from __future__ import annotations

from dataclasses import dataclass, replace
import math
from time import perf_counter

from ropeway_skip_stop_optimization.optimization.ddd.aggregate_support import (
    DddAggregateSupportCut,
    DddAggregateSupportDistanceCut,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_primal import (
    DddCpSatPrimalOracle,
    DddCpSatPrimalResult,
    DddCpSatPrimalStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_round import (
    DddCpSatMasterCoupling,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddAnonymousMasterProgress,
    DddAnonymousFlowStatus,
    DddLayeredTimeNetworkBuilder,
    DddNetworkTimeProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_refinement_config import (
    DddNetworkTimeRefinementConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_refinement_runtime import (
    DddNetworkRefinementRuntime,
)
from ropeway_skip_stop_optimization.optimization.ddd.primal_evaluation import (
    DddPrimalPoolEvaluationResult,
    DddPrimalEvaluationResult,
    DddPrimalEvaluator,
)
from ropeway_skip_stop_optimization.optimization.ddd.primal_tracking import (
    DddPrimalIncumbentTracker,
    DddPrimalRoundState,
)
from ropeway_skip_stop_optimization.optimization.ddd.passenger_master import (
    DddPassengerMasterProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.prefix_budget import (
    ddd_prefix_formulation_within_budget,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_slot import (
    DddTrajectoryColumnPool,
    DddTrajectorySlotPoolResult,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (
    DddTrajectoryWaitingDomain,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_passenger_lp import (
    DddTrajectoryPassengerLpResult,
)
from ropeway_skip_stop_optimization.optimization.ddd.resource_time import (
    DddAnonymousResourceRow,
    DddAnonymousResourceRowKind,
)
from ropeway_skip_stop_optimization.optimization.ddd.lifting import (
    build_ddd_prefix_conflict_cuts,
)
from ropeway_skip_stop_optimization.optimization.ddd.round_snapshot import (
    build_ddd_round_snapshot,
    ddd_master_diagnostic_kwargs,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceHorizonCoverageError,
    DddReferenceResourceConflictError,
    DddReferenceSolution,
    DddReferenceTrajectory,
    build_ddd_reference_visit,
    find_ddd_reference_conflicts,
    validate_ddd_reference_solution,
)
from ropeway_skip_stop_optimization.optimization.ddd.support_master import (
    DDD_CP_SAT_CABIN_PATH_CORE_PROVENANCES,
    DddSupportConflictCut,
    DddSupportSelection,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_refinement import (
    DddRecoveredSchedule,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_space import (
    DddTimeDiscretization,
    DddWaitingDiscretization,
)
from ropeway_skip_stop_optimization.optimization.ddd.timed_flow_cover import (
    DddTimedFlowCoverCut,
)


from ropeway_skip_stop_optimization.optimization.ddd.network_refinement_model import (
    DddNetworkTimeRefinementIteration,
    DddNetworkTimeRefinementProgressCallback,
    DddNetworkTimeRefinementProgressEvent,
    DddNetworkTimeRefinementProgressStage,
    DddNetworkTimeRefinementResult,
    DddNetworkTimeRefinementStatus,
    DddNetworkValidationResult,
    DddNetworkValidationStatus,
)


@dataclass(frozen=True)
class DddNetworkTimeRefinementSolver(DddNetworkTimeRefinementConfig):

    def solve(
        self,
        problem: DddNetworkTimeProblem,
        *,
        progress_callback: DddNetworkTimeRefinementProgressCallback | None = None,
        primal_evaluator: DddPrimalEvaluator | None = None,
        passenger_master_problem: DddPassengerMasterProblem | None = None,
        initial_schedules: tuple[DddRecoveredSchedule, ...] = (),
    ) -> DddNetworkTimeRefinementResult:
        solve_started = perf_counter()
        self.validate_solve_context(
            problem,
            primal_evaluator=primal_evaluator,
            passenger_master_problem=passenger_master_problem,
        )
        trajectory_pool_enabled = self.trajectory_pool_enabled
        resolved_trajectory_optimizer_mode = (
            self.resolved_trajectory_optimizer_mode
        )
        runtime = DddNetworkRefinementRuntime.build(self)
        shared_builder = runtime.network_builder
        master = runtime.flow_master
        master_phase_solver = runtime.master_phase_solver
        warm_start_projector = runtime.warm_start_projector
        decomposer = runtime.flow_decomposer
        path_adapter = runtime.path_problem_adapter
        lifting_phase_solver = runtime.lifting_phase_solver
        resource_conflict_phase_solver = runtime.resource_conflict_phase_solver
        trajectory_phase_solver = runtime.trajectory_phase_solver
        termination_policy = runtime.termination_policy
        recovery_phase_solver = runtime.recovery_phase_solver
        cp_sat_oracle = runtime.primal_oracle
        nearest_support_oracle = runtime.nearest_support_oracle
        trajectory_pricing_oracle = runtime.trajectory_pricing_oracle
        local_resource_analyzer = runtime.local_resource_analyzer
        cp_sat_round_solver = runtime.cp_sat_round_solver
        bootstrap_phase_solver = runtime.bootstrap_phase_solver
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
        bootstrap_result = None
        bootstrap_objective: float | None = None
        trajectory_column_pool = DddTrajectoryColumnPool()
        primal_tracker = DddPrimalIncumbentTracker(
            evaluator=primal_evaluator,
            trajectory_column_pool=trajectory_column_pool,
            trajectory_pool_enabled=trajectory_pool_enabled,
            remember_candidates=self.cp_sat_diversification_interval > 0,
        )
        last_trajectory_pool_fingerprint: str | None = None
        latest_trajectory_pool_result: DddTrajectorySlotPoolResult | None = None
        latest_trajectory_pool_lp_result: DddTrajectoryPassengerLpResult | None = None

        def remaining_budget() -> float | None:
            if self.total_time_limit_seconds is None:
                return None
            return max(
                0.0,
                self.total_time_limit_seconds - (perf_counter() - solve_started),
            )

        def bounded_oracle(
            oracle: DddCpSatPrimalOracle,
        ) -> DddCpSatPrimalOracle:
            remaining = remaining_budget()
            if remaining is None:
                return oracle
            return replace(
                oracle,
                time_limit_seconds=max(
                    1e-3,
                    min(getattr(oracle, "time_limit_seconds"), remaining),
                ),
            )

        def time_limit_result() -> DddNetworkTimeRefinementResult:
            return _result(
                status=(
                    DddNetworkTimeRefinementStatus.TIME_LIMIT_WITH_CERTIFIED_INTERVAL
                ),
                schedules=best_schedules,
                reference_solution=best_reference,
                lower_bound=lower_bound,
                upper_bound=upper_bound,
                iterations=iterations,
                discretization=current.discretization,
                waiting_discretization=current.waiting_discretization,
                cuts=cuts,
                primal_evaluation=best_primal_evaluation,
                aggregate_support_cuts=aggregate_support_cuts,
                aggregate_distance_cuts=aggregate_distance_cuts,
                timed_flow_cover_cuts=timed_flow_cover_cuts,
                bootstrap_result=bootstrap_result,
                bootstrap_objective=bootstrap_objective,
            )

        def budget_exhausted() -> bool:
            remaining = remaining_budget()
            return remaining is not None and remaining <= 0

        def positive_remaining_budget() -> float | None:
            remaining = remaining_budget()
            return None if remaining is None else max(1e-3, remaining)

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
                    remaining_budget_seconds=remaining_budget(),
                    iteration=iteration,
                    candidate_index=candidate_index,
                    candidate_limit=candidate_limit,
                    candidate_elapsed_seconds=candidate_elapsed_seconds,
                    primal_best_objective=primal_best_objective,
                    master_progress=master_progress,
                    global_lower_bound=_finite_or_none(lower_bound),
                    global_upper_bound=_finite_or_none(upper_bound),
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

        if initial_schedules:
            initial_validation = _validate_reference_solution(
                current,
                initial_schedules,
                tolerance_seconds=self.tolerance_seconds,
            )
            if initial_validation.solution is None:
                raise ValueError(
                    "DDD initial primal schedules are incompatible with the "
                    f"current problem: {initial_validation.detail}"
                )
            primal_tracker.consider_candidate(
                current,
                initial_schedules,
                initial_validation.solution,
                require_movement_plan=False,
                time_limit_seconds=positive_remaining_budget(),
            )
            upper_bound = primal_tracker.upper_bound
            best_schedules = primal_tracker.best_schedules
            best_reference = primal_tracker.best_reference
            best_primal_evaluation = primal_tracker.best_evaluation

        if budget_exhausted():
            return time_limit_result()

        bootstrap_phase = bootstrap_phase_solver.solve(
            problem=current,
            oracle=bounded_oracle(cp_sat_oracle),
            validate_candidate=lambda schedules: _validate_reference_solution(
                current,
                schedules,
                tolerance_seconds=self.tolerance_seconds,
            ).solution,
            consume_candidate=lambda schedules, solution: (
                primal_tracker.consider_candidate(
                    current,
                    schedules,
                    solution,
                    require_movement_plan=False,
                    time_limit_seconds=positive_remaining_budget(),
                )
            ),
            on_started=lambda: emit(
                DddNetworkTimeRefinementProgressStage.PRIMAL_BOOTSTRAP_STARTED,
                0,
            ),
            on_finished=lambda: emit(
                DddNetworkTimeRefinementProgressStage.PRIMAL_BOOTSTRAP_FINISHED,
                0,
            ),
        )
        bootstrap_result = bootstrap_phase.oracle_result
        bootstrap_objective = bootstrap_phase.objective_value
        upper_bound = primal_tracker.upper_bound
        best_schedules = primal_tracker.best_schedules
        best_reference = primal_tracker.best_reference
        best_primal_evaluation = primal_tracker.best_evaluation
        if bootstrap_phase.exact_infeasible:
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
                waiting_discretization=current.waiting_discretization,
                cuts=cuts,
                aggregate_support_cuts=aggregate_support_cuts,
                aggregate_distance_cuts=aggregate_distance_cuts,
                timed_flow_cover_cuts=timed_flow_cover_cuts,
                bootstrap_result=bootstrap_result,
            )
        if bootstrap_phase.invalid_candidate:
            return _result(
                status=DddNetworkTimeRefinementStatus.INVALID_INTERNAL,
                schedules=(),
                reference_solution=None,
                lower_bound=lower_bound,
                upper_bound=math.inf,
                iterations=iterations,
                discretization=current.discretization,
                waiting_discretization=current.waiting_discretization,
                cuts=cuts,
                aggregate_support_cuts=aggregate_support_cuts,
                aggregate_distance_cuts=aggregate_distance_cuts,
                timed_flow_cover_cuts=timed_flow_cover_cuts,
                bootstrap_result=bootstrap_result,
            )

        for round_index in range(1, self.max_iterations + 1):
            if budget_exhausted():
                return time_limit_result()
            round_started = perf_counter()
            primal_round_state = DddPrimalRoundState()
            primal_evaluation_status = primal_round_state.status
            primal_evaluation_count = primal_round_state.evaluation_count
            primal_evaluation_seconds = primal_round_state.evaluation_seconds
            round_primal_objective = primal_round_state.objective_value
            round_primal_evaluation = primal_round_state.evaluation
            primal_candidate_summaries = primal_round_state.summaries
            trajectory_pool_result = latest_trajectory_pool_result
            trajectory_pool_lp_result = latest_trajectory_pool_lp_result
            trajectory_pool_added_option_count = 0
            trajectory_pool_solved_this_round = False
            trajectory_pricing_status = DddCpSatPrimalStatus.NOT_RUN
            trajectory_pricing_preference_count = 0
            trajectory_pricing_candidate_count = 0
            trajectory_pricing_objective_value: float | None = None
            trajectory_pricing_objective_bound: float | None = None
            trajectory_pricing_signal_fingerprint: str | None = None
            trajectory_pricing_seconds = 0.0

            def sync_primal_state() -> None:
                nonlocal best_primal_evaluation
                nonlocal best_reference
                nonlocal best_schedules
                nonlocal primal_evaluation_count
                nonlocal primal_evaluation_seconds
                nonlocal primal_evaluation_status
                nonlocal round_primal_evaluation
                nonlocal round_primal_objective
                nonlocal trajectory_pool_added_option_count
                nonlocal upper_bound

                upper_bound = primal_tracker.upper_bound
                best_schedules = primal_tracker.best_schedules
                best_reference = primal_tracker.best_reference
                best_primal_evaluation = primal_tracker.best_evaluation
                primal_evaluation_status = primal_round_state.status
                primal_evaluation_count = primal_round_state.evaluation_count
                primal_evaluation_seconds = primal_round_state.evaluation_seconds
                round_primal_objective = primal_round_state.objective_value
                round_primal_evaluation = primal_round_state.evaluation
                trajectory_pool_added_option_count = (
                    primal_round_state.trajectory_pool_added_option_count
                )

            def consider_primal_candidate(
                schedules: tuple[DddRecoveredSchedule, ...],
                solution: DddReferenceSolution,
            ) -> None:
                primal_tracker.consider_candidate(
                    current,
                    schedules,
                    solution,
                    round_state=primal_round_state,
                    on_evaluated=lambda state, best_objective: emit(
                        DddNetworkTimeRefinementProgressStage.PRIMAL_EVALUATION_FINISHED,
                        round_index,
                        candidate_index=state.evaluation_count,
                        candidate_limit=cp_sat_candidate_count,
                        candidate_elapsed_seconds=state.evaluation_seconds,
                        primal_best_objective=best_objective,
                    ),
                    time_limit_seconds=positive_remaining_budget(),
                )
                sync_primal_state()

            emit(
                DddNetworkTimeRefinementProgressStage.ROUND_STARTED,
                round_index,
            )
            if active_resource_row_fingerprint != current.refinement_fingerprint:
                active_resource_rows.clear()
                active_resource_row_fingerprint = current.refinement_fingerprint
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
            if not ddd_prefix_formulation_within_budget(
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
                    waiting_discretization=current.waiting_discretization,
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
            master_phase = master_phase_solver.solve(
                master=master,
                network=network,
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
                on_master_started=lambda: emit(
                    DddNetworkTimeRefinementProgressStage.MASTER_STARTED,
                    round_index,
                ),
                on_master_progress=lambda item: emit(
                    DddNetworkTimeRefinementProgressStage.MASTER_PROGRESS,
                    round_index,
                    master_progress=item,
                ),
                on_master_finished=lambda: emit(
                    DddNetworkTimeRefinementProgressStage.MASTER_FINISHED,
                    round_index,
                ),
                on_separation_finished=lambda: emit(
                    DddNetworkTimeRefinementProgressStage.RESOURCE_WINDOW_SEPARATION_FINISHED,
                    round_index,
                ),
                time_limit_seconds=positive_remaining_budget(),
            )
            flow = master_phase.flow
            active_resource_rows = list(master_phase.active_resource_rows)
            round_resource_window_rows = list(master_phase.added_resource_rows)
            interval_resource_row_ids.update(
                row.id for row in round_resource_window_rows
            )
            master_solve_seconds = master_phase.solve_seconds
            resource_window_resolve_count = (
                master_phase.resource_window_resolve_count
            )
            resource_window_candidate_count = (
                master_phase.resource_window_candidate_count
            )
            resource_window_violated_count = (
                master_phase.resource_window_violated_count
            )
            resource_window_duplicate_count = (
                master_phase.resource_window_duplicate_count
            )
            resource_window_entry_row_count = (
                master_phase.resource_window_entry_row_count
            )
            resource_window_energy_row_count = (
                master_phase.resource_window_energy_row_count
            )
            resource_window_separation_seconds = (
                master_phase.resource_window_separation_seconds
            )
            resource_window_master_seconds = (
                master_phase.resource_window_master_seconds
            )
            resource_window_lower_bound_before = (
                master_phase.resource_window_lower_bound_before
            )
            resource_window_lower_bound_after = (
                master_phase.resource_window_lower_bound_after
            )
            if flow.status is DddAnonymousFlowStatus.TIME_LIMIT:
                if flow.best_bound is not None:
                    lower_bound = max(lower_bound, flow.best_bound)
                return time_limit_result()
            if flow.status is DddAnonymousFlowStatus.INFEASIBLE:
                record_iteration(
                    build_ddd_round_snapshot(
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
                        cell_lift_validation=DddNetworkValidationResult.not_run(),
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
                        resource_window_resolve_count=(resource_window_resolve_count),
                        resource_window_candidate_count=(
                            resource_window_candidate_count
                        ),
                        resource_window_violated_count=(resource_window_violated_count),
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
                        resource_window_master_seconds=(resource_window_master_seconds),
                        resource_window_lower_bound_before=(
                            resource_window_lower_bound_before
                        ),
                        resource_window_lower_bound_after=(
                            resource_window_lower_bound_after
                        ),
                        **ddd_master_diagnostic_kwargs(flow),
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
                    waiting_discretization=current.waiting_discretization,
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

            cp_sat_candidate_count = 0

            def consume_cp_sat_candidate(
                schedules: tuple[DddRecoveredSchedule, ...],
                solution: DddReferenceSolution,
                candidate_limit: int,
            ) -> None:
                nonlocal cp_sat_candidate_count
                cp_sat_candidate_count = candidate_limit
                consider_primal_candidate(schedules, solution)

            cp_sat_round = cp_sat_round_solver.solve(
                round_index=round_index,
                problem=current,
                network=network,
                flow=flow,
                paths=paths,
                existing_prefix_cuts=tuple(cuts),
                existing_aggregate_support_cut_ids=frozenset(
                    aggregate_support_cut_ids
                ),
                existing_aggregate_distance_cut_ids=frozenset(
                    aggregate_distance_cut_ids
                ),
                existing_timed_flow_cover_cut_ids=frozenset(
                    timed_flow_cover_cut_ids
                ),
                has_incumbent=best_reference is not None,
                best_schedules=best_schedules,
                excluded_schedules=primal_tracker.remembered_schedules,
                primal_oracle=cp_sat_oracle,
                nearest_support_oracle=nearest_support_oracle,
                local_resource_analyzer=local_resource_analyzer,
                validate_candidate=lambda schedules: _validate_reference_solution(
                    current,
                    schedules,
                    tolerance_seconds=self.tolerance_seconds,
                ).solution,
                consume_candidate=consume_cp_sat_candidate,
                on_candidate_found=lambda candidate_index, elapsed_seconds: emit(
                    DddNetworkTimeRefinementProgressStage.PRIMAL_ORACLE_CANDIDATE_FOUND,
                    round_index,
                    candidate_index=candidate_index,
                    candidate_limit=self.cp_sat_max_candidate_count,
                    candidate_elapsed_seconds=elapsed_seconds,
                ),
                on_finished=lambda: emit(
                    DddNetworkTimeRefinementProgressStage.PRIMAL_ORACLE_FINISHED,
                    round_index,
                ),
                remaining_time_seconds=remaining_budget,
            )
            cp_sat_status = cp_sat_round.status
            cp_sat_seconds = cp_sat_round.seconds
            cp_sat_conflict_count = cp_sat_round.conflict_count
            cp_sat_branch_count = cp_sat_round.branch_count
            cp_sat_candidate_count = cp_sat_round.candidate_count
            cp_sat_search_complete = cp_sat_round.search_complete
            cp_sat_exact_infeasible = cp_sat_round.exact_infeasible
            cp_sat_cabin_path_status = cp_sat_round.cabin_path_status
            cp_sat_cabin_path_seconds = cp_sat_round.cabin_path_seconds
            cp_sat_cabin_path_core_cabin_ids = (
                cp_sat_round.cabin_path_core_cabin_ids
            )
            cp_sat_cabin_path_core_literal_count = (
                cp_sat_round.cabin_path_core_literal_count
            )
            cp_sat_cabin_path_cut_literal_count = (
                cp_sat_round.cabin_path_cut_literal_count
            )
            cp_sat_cabin_path_candidate_cuts = (
                cp_sat_round.cabin_path_candidate_cuts
            )
            new_aggregate_support_cuts = cp_sat_round.aggregate_support_cuts
            new_aggregate_distance_cuts = cp_sat_round.aggregate_distance_cuts
            new_timed_flow_cover_cuts = cp_sat_round.timed_flow_cover_cuts
            aggregate_support_cuts.extend(new_aggregate_support_cuts)
            aggregate_support_cut_ids.update(
                cut.id for cut in new_aggregate_support_cuts
            )
            aggregate_distance_cuts.extend(new_aggregate_distance_cuts)
            aggregate_distance_cut_ids.update(
                cut.id for cut in new_aggregate_distance_cuts
            )
            timed_flow_cover_cuts.extend(new_timed_flow_cover_cuts)
            timed_flow_cover_cut_ids.update(
                cut.id for cut in new_timed_flow_cover_cuts
            )
            cp_sat_core_literal_count = cp_sat_round.core_literal_count
            cp_sat_timed_flow_core_literal_count = (
                cp_sat_round.timed_flow_core_literal_count
            )
            cp_sat_timed_flow_core_resource_ids = (
                cp_sat_round.timed_flow_core_resource_ids
            )
            cp_sat_local_explainability = cp_sat_round.local_explainability
            cp_sat_nearest_status = cp_sat_round.nearest_status
            cp_sat_nearest_seconds = cp_sat_round.nearest_seconds
            cp_sat_nearest_distance_primal = cp_sat_round.nearest_distance_primal
            cp_sat_nearest_distance_lower_bound = (
                cp_sat_round.nearest_distance_lower_bound
            )
            if budget_exhausted():
                return time_limit_result()
            if cp_sat_round.invalid_candidate:
                return _result(
                    status=DddNetworkTimeRefinementStatus.INVALID_INTERNAL,
                    schedules=best_schedules,
                    reference_solution=best_reference,
                    lower_bound=lower_bound,
                    upper_bound=upper_bound,
                    iterations=iterations,
                    discretization=current.discretization,
                    waiting_discretization=current.waiting_discretization,
                    cuts=cuts,
                    primal_evaluation=best_primal_evaluation,
                    aggregate_support_cuts=aggregate_support_cuts,
                    aggregate_distance_cuts=aggregate_distance_cuts,
                    timed_flow_cover_cuts=timed_flow_cover_cuts,
                    bootstrap_result=bootstrap_result,
                    bootstrap_objective=bootstrap_objective,
                )

            new_cabin_path_core_cuts = tuple(
                cut for cut in cp_sat_cabin_path_candidate_cuts if cut.id not in cut_ids
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
                    waiting_discretization=current.waiting_discretization,
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
                    build_ddd_round_snapshot(
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
                        cell_lift_validation=DddNetworkValidationResult.not_run(),
                        conflict_count=0,
                        added_cut_ids=tuple(cut.id for cut in new_cabin_path_core_cuts),
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
                        resource_window_resolve_count=(resource_window_resolve_count),
                        resource_window_candidate_count=(
                            resource_window_candidate_count
                        ),
                        resource_window_violated_count=(resource_window_violated_count),
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
                        resource_window_master_seconds=(resource_window_master_seconds),
                        resource_window_lower_bound_before=(
                            resource_window_lower_bound_before
                        ),
                        resource_window_lower_bound_after=(
                            resource_window_lower_bound_after
                        ),
                        **ddd_master_diagnostic_kwargs(flow),
                    )
                )
                continue

            recovery_phase = recovery_phase_solver.solve(
                path_problems=path_problems,
                paths=paths,
                validate_candidate=lambda schedules: _validate_reference_solution(
                    current,
                    schedules,
                    tolerance_seconds=self.tolerance_seconds,
                ),
                consume_candidate=consider_primal_candidate,
            )
            recovery_feasible = recovery_phase.feasible
            recovery_objective = recovery_phase.objective_value
            recovery_validation = recovery_phase.validation
            recovery_seconds = recovery_phase.seconds
            emit(
                DddNetworkTimeRefinementProgressStage.RECOVERY_FINISHED,
                round_index,
            )

            lifting_started = perf_counter()
            lifting_phase = lifting_phase_solver.solve(
                discretization=current.discretization,
                path_problems=path_problems,
                paths=paths,
                validate_candidate=lambda schedules: _validate_reference_solution(
                    current,
                    schedules,
                    tolerance_seconds=self.tolerance_seconds,
                ),
                consume_candidate=consider_primal_candidate,
            )
            cell_lift_statuses = lifting_phase.statuses
            cell_lift_validation = lifting_phase.validation
            time_splits = lifting_phase.time_splits
            refined_discretization = lifting_phase.refined_discretization
            refinement_stalled_detail = lifting_phase.stalled_detail
            trajectory_time_split_count = len(time_splits)
            resource_conflict_phase = resource_conflict_phase_solver.solve(
                network=network,
                paths=paths,
                validation=cell_lift_validation,
                initial_time_splits=time_splits,
                refined_discretization=refined_discretization,
                waiting_discretization=current.waiting_discretization,
                bounded_waiting=(
                    current.waiting_policy.domain
                    is DddTrajectoryWaitingDomain.BOUNDED_WAIT
                ),
                active_resource_rows=tuple(active_resource_rows),
                existing_prefix_cuts=tuple(cuts),
                existing_prefix_cut_ids=frozenset(cut_ids),
            )
            time_splits = resource_conflict_phase.time_splits
            refined_discretization = (
                resource_conflict_phase.refined_discretization
            )
            waiting_splits = resource_conflict_phase.waiting_splits
            refined_waiting_discretization = (
                resource_conflict_phase.refined_waiting_discretization
            )
            resource_time_split_count = (
                resource_conflict_phase.resource_time_split_count
            )
            new_resource_rows = resource_conflict_phase.new_resource_rows
            new_cuts = resource_conflict_phase.new_prefix_cuts
            prefix_budget_exhausted = (
                resource_conflict_phase.prefix_budget_exhausted
            )
            if resource_conflict_phase.invalid_missing_support:
                return _result(
                    status=DddNetworkTimeRefinementStatus.INVALID_INTERNAL,
                    schedules=best_schedules,
                    reference_solution=best_reference,
                    lower_bound=lower_bound,
                    upper_bound=upper_bound,
                    iterations=iterations,
                    discretization=current.discretization,
                    waiting_discretization=current.waiting_discretization,
                    cuts=cuts,
                    primal_evaluation=best_primal_evaluation,
                    aggregate_support_cuts=aggregate_support_cuts,
                    aggregate_distance_cuts=aggregate_distance_cuts,
                    timed_flow_cover_cuts=timed_flow_cover_cuts,
                    bootstrap_result=bootstrap_result,
                    bootstrap_objective=bootstrap_objective,
                )
            if (
                cell_lift_validation.status
                is DddNetworkValidationStatus.RESOURCE_CONFLICT
                and not resource_conflict_phase.has_refinement
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
                    waiting_discretization=current.waiting_discretization,
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

            def consume_trajectory_pool_evaluation(
                pool_evaluation: DddPrimalPoolEvaluationResult,
            ) -> None:
                evaluation = pool_evaluation.evaluation
                if evaluation is None:
                    return
                pool_result = pool_evaluation.pool_result
                primal_tracker.record_external_evaluation(
                    schedules=pool_result.schedules,
                    solution=pool_result.reference_solution,
                    evaluation=evaluation,
                    round_state=primal_round_state,
                )
                sync_primal_state()

            trajectory_phase = trajectory_phase_solver.solve(
                round_index=round_index,
                problem=current,
                paths=paths,
                column_pool=trajectory_column_pool,
                evaluator=primal_evaluator,
                pricing_oracle=trajectory_pricing_oracle,
                previous_pool_result=trajectory_pool_result,
                previous_pool_lp_result=trajectory_pool_lp_result,
                previous_pool_fingerprint=last_trajectory_pool_fingerprint,
                best_schedules=lambda: best_schedules,
                validate_candidate=lambda schedules: _validate_reference_solution(
                    current,
                    schedules,
                    tolerance_seconds=self.tolerance_seconds,
                ).solution,
                consume_candidate=consider_primal_candidate,
                consume_pool_evaluation=consume_trajectory_pool_evaluation,
                on_pool_started=lambda: emit(
                    DddNetworkTimeRefinementProgressStage.TRAJECTORY_POOL_STARTED,
                    round_index,
                ),
                on_pool_finished=lambda: emit(
                    DddNetworkTimeRefinementProgressStage.TRAJECTORY_POOL_FINISHED,
                    round_index,
                ),
                on_candidate_found=lambda candidate_index, elapsed_seconds: emit(
                    DddNetworkTimeRefinementProgressStage.PRIMAL_ORACLE_CANDIDATE_FOUND,
                    round_index,
                    candidate_index=candidate_index,
                    candidate_limit=self.trajectory_pricing_max_candidate_count,
                    candidate_elapsed_seconds=elapsed_seconds,
                ),
            )
            trajectory_pool_result = trajectory_phase.pool_result
            trajectory_pool_lp_result = trajectory_phase.pool_lp_result
            latest_trajectory_pool_result = trajectory_pool_result
            latest_trajectory_pool_lp_result = trajectory_pool_lp_result
            last_trajectory_pool_fingerprint = trajectory_phase.pool_fingerprint
            trajectory_pool_solved_this_round = (
                trajectory_phase.pool_solved_this_round
            )
            trajectory_pricing_status = trajectory_phase.pricing_status
            trajectory_pricing_preference_count = (
                trajectory_phase.pricing_preference_count
            )
            trajectory_pricing_candidate_count = (
                trajectory_phase.pricing_candidate_count
            )
            trajectory_pricing_objective_value = (
                trajectory_phase.pricing_objective_value
            )
            trajectory_pricing_objective_bound = (
                trajectory_phase.pricing_objective_bound
            )
            trajectory_pricing_signal_fingerprint = (
                trajectory_phase.pricing_signal_fingerprint
            )
            trajectory_pricing_seconds = trajectory_phase.pricing_seconds
            if trajectory_phase.invalid_candidate:
                return _result(
                    status=DddNetworkTimeRefinementStatus.INVALID_INTERNAL,
                    schedules=best_schedules,
                    reference_solution=best_reference,
                    lower_bound=lower_bound,
                    upper_bound=upper_bound,
                    iterations=iterations,
                    discretization=current.discretization,
                    waiting_discretization=current.waiting_discretization,
                    cuts=cuts,
                    primal_evaluation=best_primal_evaluation,
                    aggregate_support_cuts=aggregate_support_cuts,
                    aggregate_distance_cuts=aggregate_distance_cuts,
                    timed_flow_cover_cuts=timed_flow_cover_cuts,
                    bootstrap_result=bootstrap_result,
                    bootstrap_objective=bootstrap_objective,
                )
            record_iteration(
                build_ddd_round_snapshot(
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
                    cp_sat_cabin_path_core_cabin_ids=(cp_sat_cabin_path_core_cabin_ids),
                    cp_sat_cabin_path_core_literal_count=(
                        cp_sat_cabin_path_core_literal_count
                    ),
                    cp_sat_cabin_path_cut_literal_count=(
                        cp_sat_cabin_path_cut_literal_count
                    ),
                    added_cabin_path_core_cut_ids=tuple(
                        cut.id
                        for cut in new_cuts
                        if cut.provenance in DDD_CP_SAT_CABIN_PATH_CORE_PROVENANCES
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
                    trajectory_pool_lp_result=trajectory_pool_lp_result,
                    trajectory_pricing_status=trajectory_pricing_status,
                    trajectory_pricing_preference_count=(
                        trajectory_pricing_preference_count
                    ),
                    trajectory_pricing_candidate_count=(
                        trajectory_pricing_candidate_count
                    ),
                    trajectory_pricing_objective_value=(
                        trajectory_pricing_objective_value
                    ),
                    trajectory_pricing_objective_bound=(
                        trajectory_pricing_objective_bound
                    ),
                    trajectory_pricing_signal_fingerprint=(
                        trajectory_pricing_signal_fingerprint
                    ),
                    trajectory_pricing_seconds=trajectory_pricing_seconds,
                    trajectory_optimizer_mode=resolved_trajectory_optimizer_mode,
                    trajectory_pool_candidate_count=(
                        trajectory_column_pool.candidate_count
                    ),
                    trajectory_pool_added_option_count=(
                        trajectory_pool_added_option_count
                    ),
                    trajectory_pool_option_count=(trajectory_column_pool.column_count),
                    trajectory_pool_solved_this_round=(
                        trajectory_pool_solved_this_round
                    ),
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
                    resource_window_candidate_count=(resource_window_candidate_count),
                    resource_window_violated_count=(resource_window_violated_count),
                    resource_window_duplicate_count=(resource_window_duplicate_count),
                    resource_window_added_count=len(round_resource_window_rows),
                    resource_window_entry_row_count=(resource_window_entry_row_count),
                    resource_window_energy_row_count=(resource_window_energy_row_count),
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
                    waiting_splits=waiting_splits,
                    **ddd_master_diagnostic_kwargs(flow),
                )
            )
            termination = termination_policy.decide(
                cp_sat_exact_infeasible=cp_sat_exact_infeasible,
                has_incumbent=best_reference is not None,
                refinement_stalled=refinement_stalled_detail is not None,
                time_split_count=len(time_splits) + len(waiting_splits),
                new_prefix_cut_count=len(new_cuts),
                new_resource_row_count=len(new_resource_rows),
                new_aggregate_support_cut_count=len(new_aggregate_support_cuts),
                trajectory_pool_added_option_count=(
                    trajectory_pool_added_option_count
                ),
                lower_bound=lower_bound,
                upper_bound=upper_bound,
            )
            if termination.status is not None:
                return _result(
                    status=termination.status,
                    schedules=best_schedules,
                    reference_solution=best_reference,
                    lower_bound=lower_bound,
                    upper_bound=termination.upper_bound,
                    iterations=iterations,
                    discretization=current.discretization,
                    waiting_discretization=current.waiting_discretization,
                    cuts=cuts,
                    primal_evaluation=(
                        None
                        if termination.clear_primal_evaluation
                        else best_primal_evaluation
                    ),
                    aggregate_support_cuts=aggregate_support_cuts,
                    aggregate_distance_cuts=aggregate_distance_cuts,
                    timed_flow_cover_cuts=timed_flow_cover_cuts,
                    bootstrap_result=bootstrap_result,
                    bootstrap_objective=bootstrap_objective,
                )
            if time_splits:
                current = current.with_discretization(refined_discretization)
            if waiting_splits:
                current = current.with_waiting_discretization(
                    refined_waiting_discretization
                )

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
            waiting_discretization=current.waiting_discretization,
            cuts=cuts,
            primal_evaluation=best_primal_evaluation,
            aggregate_support_cuts=aggregate_support_cuts,
            aggregate_distance_cuts=aggregate_distance_cuts,
            timed_flow_cover_cuts=timed_flow_cover_cuts,
            bootstrap_result=bootstrap_result,
            bootstrap_objective=bootstrap_objective,
        )


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
                    wait_seconds=(
                        schedule.events[visit_index + 1].time_seconds
                        - schedule.events[visit_index].time_seconds
                        - options_by_id[option_id].duration_seconds
                    ),
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
            waiting_policy=problem.waiting_policy,
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


def _result(
    *,
    status: DddNetworkTimeRefinementStatus,
    schedules: tuple[DddRecoveredSchedule, ...],
    reference_solution: DddReferenceSolution | None,
    lower_bound: float,
    upper_bound: float,
    iterations: list[DddNetworkTimeRefinementIteration],
    discretization: DddTimeDiscretization,
    waiting_discretization: DddWaitingDiscretization,
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
        final_waiting_discretization=waiting_discretization,
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
