from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math

from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddAnonymousFlowDecomposer,
    DddAnonymousFlowMaster,
    DddAnonymousFlowStatus,
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
)
from ropeway_skip_stop_optimization.optimization.ddd.time_space import (
    DddTimeDiscretization,
)


class DddNetworkTimeRefinementStatus(StrEnum):
    OPTIMAL = "optimal"
    FEASIBLE_WITH_GAP = "feasible_with_gap"
    UNKNOWN_NO_INCUMBENT = "unknown_no_incumbent"
    RELAXATION_INFEASIBLE = "relaxation_infeasible"
    INVALID_INTERNAL = "invalid_internal"


class DddNetworkValidationStatus(StrEnum):
    """Outcome of validation against the complete physical movement problem."""

    NOT_RUN = "not_run"
    FEASIBLE = "feasible"
    HORIZON_INCOMPLETE = "horizon_incomplete"
    RESOURCE_CONFLICT = "resource_conflict"
    INVALID = "invalid"


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
    split_state_id: str | None
    split_boundary_seconds: float | None


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

    def solve(
        self,
        problem: DddNetworkTimeProblem,
    ) -> DddNetworkTimeRefinementResult:
        problem.validate()
        if self.max_iterations <= 0:
            raise ValueError("DDD network refinement max_iterations must be positive")
        if self.max_new_cuts_per_iteration <= 0:
            raise ValueError(
                "DDD network refinement max_new_cuts_per_iteration must be positive"
            )
        if self.tolerance_seconds < 0 or self.bound_tolerance < 0:
            raise ValueError("DDD network refinement tolerances must be nonnegative")
        builder = DddLayeredTimeNetworkBuilder(
            tolerance_seconds=self.tolerance_seconds
        )
        master = DddAnonymousFlowMaster(output_flag=self.output_flag)
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

        for round_index in range(1, self.max_iterations + 1):
            network = builder.build(current)
            flow = master.solve(network, cuts=tuple(cuts))
            if flow.status is DddAnonymousFlowStatus.INFEASIBLE:
                iterations.append(
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
                        inconsistency=None,
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
            paths = decomposer.decompose(network, flow)
            path_problems = tuple(
                path_adapter.build(current, path) for path in paths
            )

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

            cell_lift_statuses: list[DddStrictTimeLiftStatus] = []
            cell_lift_schedules: list[DddRecoveredSchedule] = []
            inconsistencies: list[DddEventCellInconsistency] = []
            for path_problem, path in zip(path_problems, paths, strict=True):
                cell_lift = cell_lifter.lift(path_problem, path)
                cell_lift_statuses.append(cell_lift.status)
                if cell_lift.schedule is not None:
                    cell_lift_schedules.append(cell_lift.schedule)
                if cell_lift.inconsistency is not None:
                    inconsistencies.append(cell_lift.inconsistency)
            cell_lift_validation = _not_run_validation()
            if len(cell_lift_schedules) == len(paths):
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

            inconsistency = min(
                inconsistencies,
                key=lambda item: (
                    item.state_id,
                    item.split_boundary_seconds,
                    item.selected_cell_id,
                ),
                default=None,
            )
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
            iterations.append(
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
                    inconsistency=inconsistency,
                )
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
            if inconsistency is None and not new_cuts:
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
            if inconsistency is not None:
                current = current.with_discretization(
                    current.discretization.split(
                        state_id=inconsistency.state_id,
                        boundary_seconds=inconsistency.split_boundary_seconds,
                        tolerance_seconds=self.tolerance_seconds,
                    )
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
    inconsistency: DddEventCellInconsistency | None,
) -> DddNetworkTimeRefinementIteration:
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
        split_state_id=(inconsistency.state_id if inconsistency else None),
        split_boundary_seconds=(
            inconsistency.split_boundary_seconds if inconsistency else None
        ),
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
