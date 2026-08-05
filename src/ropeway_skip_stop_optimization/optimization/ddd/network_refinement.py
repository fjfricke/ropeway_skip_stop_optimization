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
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution,
    DddReferenceTrajectory,
    build_ddd_reference_visit,
    validate_ddd_reference_solution,
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


@dataclass(frozen=True)
class DddNetworkTimeRefinementIteration:
    round_index: int
    discretization_fingerprint: str
    node_count: int
    arc_count: int
    variable_count: int
    constraint_count: int
    decomposed_path_count: int
    master_lower_bound: float | None
    global_lower_bound: float | None
    recovery_feasible: bool
    recovery_objective: float | None
    global_upper_bound: float | None
    strict_lift_statuses: tuple[DddStrictTimeLiftStatus, ...]
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


@dataclass(frozen=True)
class DddNetworkTimeRefinementSolver:
    max_iterations: int = 100
    tolerance_seconds: float = 1e-9
    bound_tolerance: float = 1e-9
    output_flag: bool = False

    def solve(
        self,
        problem: DddNetworkTimeProblem,
    ) -> DddNetworkTimeRefinementResult:
        problem.validate()
        if self.max_iterations <= 0:
            raise ValueError("DDD network refinement max_iterations must be positive")
        if self.tolerance_seconds < 0 or self.bound_tolerance < 0:
            raise ValueError("DDD network refinement tolerances must be nonnegative")
        builder = DddLayeredTimeNetworkBuilder(
            tolerance_seconds=self.tolerance_seconds
        )
        master = DddAnonymousFlowMaster(output_flag=self.output_flag)
        decomposer = DddAnonymousFlowDecomposer()
        path_adapter = DddNetworkPathProblemAdapter()
        lifter = DddStrictTimeCellLifter(
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

        for round_index in range(1, self.max_iterations + 1):
            network = builder.build(current)
            flow = master.solve(network)
            if flow.status is DddAnonymousFlowStatus.INFEASIBLE:
                iterations.append(
                    _iteration(
                        round_index=round_index,
                        problem=current,
                        node_count=len(network.nodes),
                        arc_count=len(network.arcs),
                        variable_count=flow.variable_count,
                        constraint_count=flow.constraint_count,
                        path_count=0,
                        master_bound=None,
                        lower_bound=lower_bound,
                        recovery_feasible=False,
                        recovery_objective=None,
                        upper_bound=upper_bound,
                        strict_statuses=(),
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
            if recovery_feasible:
                recovered_reference = _validated_reference_solution(
                    current,
                    tuple(recovered_schedules),
                    tolerance_seconds=self.tolerance_seconds,
                )
                if recovered_reference is None:
                    recovery_feasible = False
                else:
                    recovery_objective = sum(
                        schedule.objective_value
                        for schedule in recovered_schedules
                    )
                    if recovery_objective < upper_bound:
                        upper_bound = recovery_objective
                        best_schedules = tuple(recovered_schedules)
                        best_reference = recovered_reference

            strict_statuses: list[DddStrictTimeLiftStatus] = []
            strict_schedules: list[DddRecoveredSchedule] = []
            inconsistencies: list[DddEventCellInconsistency] = []
            for path_problem, path in zip(path_problems, paths, strict=True):
                strict = lifter.lift(path_problem, path)
                strict_statuses.append(strict.status)
                if strict.schedule is not None:
                    strict_schedules.append(strict.schedule)
                if strict.inconsistency is not None:
                    inconsistencies.append(strict.inconsistency)
            if len(strict_schedules) == len(paths):
                strict_reference = _validated_reference_solution(
                    current,
                    tuple(strict_schedules),
                    tolerance_seconds=self.tolerance_seconds,
                )
                if strict_reference is not None:
                    strict_objective = sum(
                        schedule.objective_value for schedule in strict_schedules
                    )
                    if strict_objective < upper_bound:
                        upper_bound = strict_objective
                        best_schedules = tuple(strict_schedules)
                        best_reference = strict_reference

            inconsistency = min(
                inconsistencies,
                key=lambda item: (
                    item.state_id,
                    item.split_boundary_seconds,
                    item.selected_cell_id,
                ),
                default=None,
            )
            iterations.append(
                _iteration(
                    round_index=round_index,
                    problem=current,
                    node_count=len(network.nodes),
                    arc_count=len(network.arcs),
                    variable_count=flow.variable_count,
                    constraint_count=flow.constraint_count,
                    path_count=len(paths),
                    master_bound=flow.best_bound,
                    lower_bound=lower_bound,
                    recovery_feasible=recovery_feasible,
                    recovery_objective=recovery_objective,
                    upper_bound=upper_bound,
                    strict_statuses=tuple(strict_statuses),
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
                )
            if inconsistency is None:
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
                )
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
        )


def _validated_reference_solution(
    problem: DddNetworkTimeProblem,
    schedules: tuple[DddRecoveredSchedule, ...],
    *,
    tolerance_seconds: float,
) -> DddReferenceSolution | None:
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
    except (KeyError, ValueError):
        return None
    return solution


def _iteration(
    *,
    round_index: int,
    problem: DddNetworkTimeProblem,
    node_count: int,
    arc_count: int,
    variable_count: int,
    constraint_count: int,
    path_count: int,
    master_bound: float | None,
    lower_bound: float,
    recovery_feasible: bool,
    recovery_objective: float | None,
    upper_bound: float,
    strict_statuses: tuple[DddStrictTimeLiftStatus, ...],
    inconsistency: DddEventCellInconsistency | None,
) -> DddNetworkTimeRefinementIteration:
    return DddNetworkTimeRefinementIteration(
        round_index=round_index,
        discretization_fingerprint=problem.discretization.fingerprint,
        node_count=node_count,
        arc_count=arc_count,
        variable_count=variable_count,
        constraint_count=constraint_count,
        decomposed_path_count=path_count,
        master_lower_bound=master_bound,
        global_lower_bound=_finite_or_none(lower_bound),
        recovery_feasible=recovery_feasible,
        recovery_objective=recovery_objective,
        global_upper_bound=_finite_or_none(upper_bound),
        strict_lift_statuses=strict_statuses,
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
    )


def _finite_or_none(value: float) -> float | None:
    return value if math.isfinite(value) else None
