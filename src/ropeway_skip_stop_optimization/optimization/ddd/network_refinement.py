from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import math
from time import perf_counter

from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddAnonymousFlowDecomposer,
    DddAnonymousFlowMaster,
    DddAnonymousFlowStatus,
    DddAnonymousFlowWarmStartProjector,
    DddLayeredTimeNetworkBuilder,
    DddNetworkPathProblemAdapter,
    DddNetworkTimeProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.lifting import (
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
    DddTimeDiscretization,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_quantize_time_seconds,
    ddd_seconds_to_tick,
)


class DddNetworkTimeRefinementStatus(StrEnum):
    OPTIMAL = "optimal"
    FEASIBLE_WITH_GAP = "feasible_with_gap"
    UNKNOWN_NO_INCUMBENT = "unknown_no_incumbent"
    RELAXATION_INFEASIBLE = "relaxation_infeasible"
    REFINEMENT_STALLED = "refinement_stalled"
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
    ROUND_STARTED = "round_started"
    NETWORK_BUILT = "network_built"
    MASTER_STARTED = "master_started"
    MASTER_FINISHED = "master_finished"
    DECOMPOSITION_FINISHED = "decomposition_finished"
    RECOVERY_FINISHED = "recovery_finished"
    LIFTING_FINISHED = "lifting_finished"
    ROUND_FINISHED = "round_finished"


@dataclass(frozen=True)
class DddNetworkTimeRefinementProgressEvent:
    stage: DddNetworkTimeRefinementProgressStage
    round_index: int
    max_iterations: int
    total_elapsed_seconds: float
    iteration: DddNetworkTimeRefinementIteration | None = None


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

    def solve(
        self,
        problem: DddNetworkTimeProblem,
        *,
        progress_callback: DddNetworkTimeRefinementProgressCallback | None = None,
    ) -> DddNetworkTimeRefinementResult:
        problem.validate()
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
        if self.tolerance_seconds < 0 or self.bound_tolerance < 0:
            raise ValueError("DDD network refinement tolerances must be nonnegative")
        shared_builder = DddLayeredTimeNetworkBuilder(
            tolerance_seconds=self.tolerance_seconds
        )
        master = DddAnonymousFlowMaster(output_flag=self.output_flag)
        warm_start_projector = DddAnonymousFlowWarmStartProjector()
        decomposer = DddAnonymousFlowDecomposer()
        path_adapter = DddNetworkPathProblemAdapter()
        cell_lifter = DddStrictTimeCellLifter(
            tolerance_seconds=self.tolerance_seconds
        )
        recovery = DddCellFreeSupportRecovery(
            tolerance_seconds=self.tolerance_seconds
        )
        current = problem
        lower_bound = -math.inf
        upper_bound = math.inf
        best_schedules: tuple[DddRecoveredSchedule, ...] = ()
        best_reference: DddReferenceSolution | None = None
        iterations: list[DddNetworkTimeRefinementIteration] = []
        cuts: list[DddSupportConflictCut] = []
        cut_ids: set[str] = set()
        previous_paths = ()
        solve_started = perf_counter()

        def emit(
            stage: DddNetworkTimeRefinementProgressStage,
            round_index: int,
            *,
            iteration: DddNetworkTimeRefinementIteration | None = None,
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

        for round_index in range(1, self.max_iterations + 1):
            round_started = perf_counter()
            emit(
                DddNetworkTimeRefinementProgressStage.ROUND_STARTED,
                round_index,
            )
            network_started = perf_counter()
            builder = (
                shared_builder
                if self.reuse_network_fragments
                else DddLayeredTimeNetworkBuilder(
                    tolerance_seconds=self.tolerance_seconds
                )
            )
            network = builder.build(current)
            network_build_seconds = perf_counter() - network_started
            emit(
                DddNetworkTimeRefinementProgressStage.NETWORK_BUILT,
                round_index,
            )
            master_started = perf_counter()
            emit(
                DddNetworkTimeRefinementProgressStage.MASTER_STARTED,
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
            flow = master.solve(
                network,
                cuts=active_cuts,
                warm_start=warm_start,
            )
            master_solve_seconds = perf_counter() - master_started
            emit(
                DddNetworkTimeRefinementProgressStage.MASTER_FINISHED,
                round_index,
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
                        tracked_prefix_cabin_count=(
                            flow.tracked_prefix_cabin_count
                        ),
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
                        recovery_validation_status=(
                            DddNetworkValidationStatus.NOT_RUN
                        ),
                        upper_bound=upper_bound,
                        cell_lift_statuses=(),
                        cell_lift_validation=_not_run_validation(),
                        conflict_count=0,
                        added_cut_ids=(),
                        total_conflict_cut_count=len(cuts),
                        time_splits=(),
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
                )
            if flow.best_bound is None:
                raise RuntimeError("optimal DDD network flow returned no best bound")
            lower_bound = max(lower_bound, flow.best_bound)
            decomposition_started = perf_counter()
            paths = decomposer.decompose(network, flow)
            previous_paths = paths
            path_problems = tuple(
                path_adapter.build(current, path) for path in paths
            )
            decomposition_seconds = perf_counter() - decomposition_started
            emit(
                DddNetworkTimeRefinementProgressStage.DECOMPOSITION_FINISHED,
                round_index,
            )

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
                        schedule.objective_value
                        for schedule in recovered_schedules
                    )
                    if recovery_objective < upper_bound:
                        upper_bound = recovery_objective
                        best_schedules = tuple(recovered_schedules)
                        best_reference = recovery_validation.solution
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
                if cell_lift.inconsistency is not None:
                    inconsistencies.append(cell_lift.inconsistency)
            time_splits, refined_discretization = _build_time_split_batch(
                current.discretization,
                tuple(inconsistencies),
                max_splits=self.max_new_time_splits_per_iteration,
                tolerance_seconds=self.tolerance_seconds,
            )
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
                    cell_lift_objective = sum(
                        schedule.objective_value for schedule in cell_lift_schedules
                    )
                    if cell_lift_objective < upper_bound:
                        upper_bound = cell_lift_objective
                        best_schedules = tuple(cell_lift_schedules)
                        best_reference = cell_lift_validation.solution

            new_cuts = tuple(
                cut
                for cut in cell_lift_validation.cuts
                if cut.id not in cut_ids
            )[: self.max_new_cuts_per_iteration]
            if (
                cell_lift_validation.status
                is DddNetworkValidationStatus.RESOURCE_CONFLICT
                and not new_cuts
            ):
                return _result(
                    status=DddNetworkTimeRefinementStatus.INVALID_INTERNAL,
                    schedules=best_schedules,
                    reference_solution=best_reference,
                    lower_bound=lower_bound,
                    upper_bound=upper_bound,
                    iterations=iterations,
                    discretization=current.discretization,
                    cuts=cuts,
                )
            cuts.extend(new_cuts)
            cut_ids.update(cut.id for cut in new_cuts)
            lifting_and_validation_seconds = perf_counter() - lifting_started
            emit(
                DddNetworkTimeRefinementProgressStage.LIFTING_FINISHED,
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
                    tracked_prefix_cabin_count=(
                        flow.tracked_prefix_cabin_count
                    ),
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
                    lifting_and_validation_seconds=(
                        lifting_and_validation_seconds
                    ),
                    round_seconds=perf_counter() - round_started,
                )
            )
            if (
                refinement_stalled_detail is not None
                and not time_splits
                and not new_cuts
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
                )
            if not time_splits and not new_cuts:
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
) -> DddNetworkTimeRefinementIteration:
    max_visit_by_cabin: dict[int, int] = {}
    for cut in cuts:
        for literal in cut.literals:
            max_visit_by_cabin[literal.cabin_id] = max(
                max_visit_by_cabin.get(literal.cabin_id, 0),
                literal.visit_index,
            )
    positive_depths = tuple(
        value for value in max_visit_by_cabin.values() if value > 0
    )
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
            sum(positive_depths) / len(positive_depths)
            if positive_depths
            else 0.0
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
    )


def _finite_or_none(value: float) -> float | None:
    return value if math.isfinite(value) else None
