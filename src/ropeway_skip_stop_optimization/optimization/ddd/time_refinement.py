from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math

from ropeway_skip_stop_optimization.optimization.ddd.time_space import (
    DddPartialTimedPath,
    DddPartialTimeMaster,
    DddPartialTimeMasterStatus,
    DddPartialTimeProblem,
    DddTimeDiscretization,
    ddd_normalize_time_seconds,
)


@dataclass(frozen=True)
class DddExactTimedEvent:
    event_index: int
    state_id: str
    time_seconds: float


@dataclass(frozen=True)
class DddRecoveredSchedule:
    cabin_id: int
    route_option_ids: tuple[str, ...]
    events: tuple[DddExactTimedEvent, ...]
    objective_value: float

    @property
    def terminal_time_seconds(self) -> float:
        if not self.events:
            raise ValueError("DDD recovered schedule has no events")
        return self.events[-1].time_seconds


def validate_ddd_recovered_schedule(
    problem: DddPartialTimeProblem,
    schedule: DddRecoveredSchedule,
    *,
    tolerance_seconds: float = 1e-9,
) -> None:
    problem.validate()
    if tolerance_seconds < 0:
        raise ValueError("DDD recovery validation tolerance must be nonnegative")
    start = problem.movement_problem.starts[0]
    if schedule.cabin_id != start.cabin_id:
        raise ValueError("DDD recovered schedule cabin does not match fixed start")
    if len(schedule.events) != len(schedule.route_option_ids) + 1:
        raise ValueError("DDD recovered schedule event and route counts differ")
    if len(schedule.route_option_ids) > start.max_visit_count:
        raise ValueError("DDD recovered schedule exceeds certified visit bound")
    if not schedule.events:
        raise ValueError("DDD recovered schedule must contain events")
    first = schedule.events[0]
    if first.event_index != 0 or first.state_id != start.state_id or not math.isclose(
        first.time_seconds,
        start.time_seconds,
        rel_tol=0.0,
        abs_tol=tolerance_seconds,
    ):
        raise ValueError("DDD recovered schedule start is inconsistent")
    options_by_id = {
        option.id: option for option in problem.movement_problem.route_options
    }
    for index, option_id in enumerate(schedule.route_option_ids):
        if option_id not in options_by_id:
            raise ValueError("DDD recovered schedule references an unknown route")
        option = options_by_id[option_id]
        source = schedule.events[index]
        target = schedule.events[index + 1]
        if source.event_index != index or target.event_index != index + 1:
            raise ValueError("DDD recovered event indices must be contiguous")
        if source.state_id != option.from_state_id or target.state_id != option.to_state_id:
            raise ValueError("DDD recovered route chain is inconsistent")
        if source.time_seconds > (
            problem.movement_problem.operational_end_seconds + tolerance_seconds
        ):
            raise ValueError("DDD recovered route departs after operational horizon")
        if not math.isclose(
            target.time_seconds,
            source.time_seconds + option.duration_seconds,
            rel_tol=0.0,
            abs_tol=tolerance_seconds,
        ):
            raise ValueError("DDD recovered route duration is inconsistent")
    if schedule.events[-1].state_id != problem.terminal_state_id:
        raise ValueError("DDD recovered schedule does not reach terminal state")
    expected_objective = problem.objective.exact_value(
        schedule.route_option_ids,
        schedule.terminal_time_seconds,
        tolerance_seconds=tolerance_seconds,
    )
    if not math.isclose(
        schedule.objective_value,
        expected_objective,
        rel_tol=0.0,
        abs_tol=tolerance_seconds,
    ):
        raise ValueError("DDD recovered schedule objective is inconsistent")


class DddPrimalRecoveryStatus(StrEnum):
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"


@dataclass(frozen=True)
class DddPrimalRecoveryResult:
    status: DddPrimalRecoveryStatus
    schedule: DddRecoveredSchedule | None


@dataclass(frozen=True)
class DddCellFreeSupportRecovery:
    tolerance_seconds: float = 1e-9

    def recover(
        self,
        problem: DddPartialTimeProblem,
        path: DddPartialTimedPath,
    ) -> DddPrimalRecoveryResult:
        problem.validate()
        try:
            schedule = _propagate_route_support(
                problem,
                path,
                tolerance_seconds=self.tolerance_seconds,
            )
            validate_ddd_recovered_schedule(
                problem,
                schedule,
                tolerance_seconds=self.tolerance_seconds,
            )
        except ValueError:
            return DddPrimalRecoveryResult(
                status=DddPrimalRecoveryStatus.INFEASIBLE,
                schedule=None,
            )
        return DddPrimalRecoveryResult(
            status=DddPrimalRecoveryStatus.FEASIBLE,
            schedule=schedule,
        )


class DddStrictTimeLiftStatus(StrEnum):
    FEASIBLE = "feasible"
    EVENT_CELL_INCONSISTENCY = "event_cell_inconsistency"


@dataclass(frozen=True)
class DddEventCellInconsistency:
    state_id: str
    selected_cell_id: str
    exact_source_time_seconds: float
    required_source_lower_seconds: float
    required_source_upper_seconds: float
    split_boundary_seconds: float
    failed_target_cell_id: str


@dataclass(frozen=True)
class DddStrictTimeLiftResult:
    status: DddStrictTimeLiftStatus
    schedule: DddRecoveredSchedule | None
    inconsistency: DddEventCellInconsistency | None


@dataclass(frozen=True)
class DddStrictTimeCellLifter:
    tolerance_seconds: float = 1e-9

    def lift(
        self,
        problem: DddPartialTimeProblem,
        path: DddPartialTimedPath,
    ) -> DddStrictTimeLiftResult:
        problem.validate()
        if self.tolerance_seconds < 0:
            raise ValueError("DDD strict lift tolerance must be nonnegative")
        schedule = _propagate_route_support(
            problem,
            path,
            tolerance_seconds=self.tolerance_seconds,
        )
        options_by_id = {
            option.id: option for option in problem.movement_problem.route_options
        }
        for arc, source_event, target_event in zip(
            path.arcs,
            schedule.events[:-1],
            schedule.events[1:],
            strict=True,
        ):
            if arc.source_cell_id is not None:
                source_cell = problem.discretization.partition(
                    arc.from_state_id
                ).cells
                selected_source_cell = next(
                    (cell for cell in source_cell if cell.id == arc.source_cell_id),
                    None,
                )
                if selected_source_cell is None or not selected_source_cell.contains(
                    source_event.time_seconds,
                    tolerance_seconds=self.tolerance_seconds,
                ):
                    raise ValueError("DDD strict lift source cell is inconsistent")
                if source_event.time_seconds > (
                    problem.movement_problem.operational_end_seconds
                    + self.tolerance_seconds
                ):
                    split_boundary = ddd_normalize_time_seconds(
                        source_event.time_seconds
                    )
                    if not (
                        selected_source_cell.lower_seconds + self.tolerance_seconds
                        < split_boundary
                        < selected_source_cell.upper_seconds
                        - self.tolerance_seconds
                    ):
                        raise ValueError(
                            "DDD post-horizon inconsistency has no interior boundary"
                        )
                    return DddStrictTimeLiftResult(
                        status=(
                            DddStrictTimeLiftStatus.EVENT_CELL_INCONSISTENCY
                        ),
                        schedule=None,
                        inconsistency=DddEventCellInconsistency(
                            state_id=arc.from_state_id,
                            selected_cell_id=selected_source_cell.id,
                            exact_source_time_seconds=(
                                source_event.time_seconds
                            ),
                            required_source_lower_seconds=(
                                problem.movement_problem.operational_end_seconds
                            ),
                            required_source_upper_seconds=split_boundary,
                            split_boundary_seconds=split_boundary,
                            failed_target_cell_id=arc.target_cell.id,
                        ),
                    )
            if arc.target_cell.contains(
                target_event.time_seconds,
                tolerance_seconds=self.tolerance_seconds,
            ):
                continue
            if arc.source_cell_id is None:
                raise ValueError("fixed-start partial arc was not exactly compatible")
            selected_source_cell = next(
                cell
                for cell in problem.discretization.partition(arc.from_state_id).cells
                if cell.id == arc.source_cell_id
            )
            option = options_by_id[arc.route_option_id]
            required_lower = ddd_normalize_time_seconds(
                arc.target_cell.lower_seconds - option.duration_seconds
            )
            required_upper = ddd_normalize_time_seconds(
                arc.target_cell.upper_seconds - option.duration_seconds
            )
            split_boundary = ddd_normalize_time_seconds(
                required_lower
                if source_event.time_seconds < required_lower
                else required_upper
            )
            if not (
                selected_source_cell.lower_seconds + self.tolerance_seconds
                < split_boundary
                < selected_source_cell.upper_seconds - self.tolerance_seconds
            ):
                raise ValueError(
                    "DDD event-cell inconsistency has no interior source boundary"
                )
            return DddStrictTimeLiftResult(
                status=DddStrictTimeLiftStatus.EVENT_CELL_INCONSISTENCY,
                schedule=None,
                inconsistency=DddEventCellInconsistency(
                    state_id=arc.from_state_id,
                    selected_cell_id=selected_source_cell.id,
                    exact_source_time_seconds=source_event.time_seconds,
                    required_source_lower_seconds=required_lower,
                    required_source_upper_seconds=required_upper,
                    split_boundary_seconds=split_boundary,
                    failed_target_cell_id=arc.target_cell.id,
                ),
            )

        validate_ddd_recovered_schedule(
            problem,
            schedule,
            tolerance_seconds=self.tolerance_seconds,
        )
        return DddStrictTimeLiftResult(
            status=DddStrictTimeLiftStatus.FEASIBLE,
            schedule=schedule,
            inconsistency=None,
        )


def _propagate_route_support(
    problem: DddPartialTimeProblem,
    path: DddPartialTimedPath,
    *,
    tolerance_seconds: float,
) -> DddRecoveredSchedule:
    start = problem.movement_problem.starts[0]
    if path.cabin_id != start.cabin_id:
        raise ValueError("DDD partial path cabin does not match fixed start")
    options_by_id = {
        option.id: option for option in problem.movement_problem.route_options
    }
    events = [DddExactTimedEvent(0, start.state_id, start.time_seconds)]
    state_id = start.state_id
    time_seconds = start.time_seconds
    for index, option_id in enumerate(path.route_option_ids):
        option = options_by_id.get(option_id)
        if option is None or option.from_state_id != state_id:
            raise ValueError("DDD partial path route support is inconsistent")
        time_seconds += option.duration_seconds
        state_id = option.to_state_id
        events.append(DddExactTimedEvent(index + 1, state_id, time_seconds))
    objective_value = problem.objective.exact_value(
        path.route_option_ids,
        time_seconds,
        tolerance_seconds=tolerance_seconds,
    )
    return DddRecoveredSchedule(
        cabin_id=start.cabin_id,
        route_option_ids=path.route_option_ids,
        events=tuple(events),
        objective_value=objective_value,
    )


class DddTimeRefinementStatus(StrEnum):
    OPTIMAL = "optimal"
    FEASIBLE_WITH_GAP = "feasible_with_gap"
    UNKNOWN_NO_INCUMBENT = "unknown_no_incumbent"
    RELAXATION_INFEASIBLE = "relaxation_infeasible"
    INVALID_INTERNAL = "invalid_internal"


@dataclass(frozen=True)
class DddTimeRefinementIteration:
    round_index: int
    discretization_fingerprint: str
    candidate_path_count: int
    selected_path_fingerprint: str | None
    master_lower_bound: float | None
    global_lower_bound: float | None
    strict_lift_status: DddStrictTimeLiftStatus | None
    recovery_status: DddPrimalRecoveryStatus | None
    recovery_objective: float | None
    global_upper_bound: float | None
    split_state_id: str | None
    split_boundary_seconds: float | None


@dataclass(frozen=True)
class DddTimeRefinementResult:
    status: DddTimeRefinementStatus
    solution: DddRecoveredSchedule | None
    global_lower_bound: float | None
    global_upper_bound: float | None
    absolute_gap: float | None
    iterations: tuple[DddTimeRefinementIteration, ...]
    final_discretization: DddTimeDiscretization


@dataclass(frozen=True)
class DddTimeRefinementSolver:
    max_iterations: int = 100
    tolerance_seconds: float = 1e-9
    bound_tolerance: float = 1e-9

    def solve(self, problem: DddPartialTimeProblem) -> DddTimeRefinementResult:
        problem.validate()
        if self.max_iterations <= 0:
            raise ValueError("DDD time refinement max_iterations must be positive")
        master = DddPartialTimeMaster(tolerance_seconds=self.tolerance_seconds)
        lifter = DddStrictTimeCellLifter(tolerance_seconds=self.tolerance_seconds)
        recovery = DddCellFreeSupportRecovery(
            tolerance_seconds=self.tolerance_seconds
        )
        current = problem
        lower_bound = -math.inf
        upper_bound = math.inf
        best_schedule: DddRecoveredSchedule | None = None
        iterations: list[DddTimeRefinementIteration] = []

        for round_index in range(1, self.max_iterations + 1):
            master_result = master.solve(current)
            if master_result.status is DddPartialTimeMasterStatus.INFEASIBLE:
                iterations.append(
                    DddTimeRefinementIteration(
                        round_index=round_index,
                        discretization_fingerprint=current.discretization.fingerprint,
                        candidate_path_count=0,
                        selected_path_fingerprint=None,
                        master_lower_bound=None,
                        global_lower_bound=_finite_or_none(lower_bound),
                        strict_lift_status=None,
                        recovery_status=None,
                        recovery_objective=None,
                        global_upper_bound=_finite_or_none(upper_bound),
                        split_state_id=None,
                        split_boundary_seconds=None,
                    )
                )
                return _result(
                    status=(
                        DddTimeRefinementStatus.INVALID_INTERNAL
                        if best_schedule is not None
                        else DddTimeRefinementStatus.RELAXATION_INFEASIBLE
                    ),
                    solution=best_schedule,
                    lower_bound=lower_bound,
                    upper_bound=upper_bound,
                    iterations=iterations,
                    discretization=current.discretization,
                )
            path = master_result.path
            master_bound = master_result.objective_lower_bound
            if path is None or master_bound is None:
                raise RuntimeError("optimal DDD partial master returned no path or bound")
            lower_bound = max(lower_bound, master_bound)

            recovered = recovery.recover(current, path)
            recovery_objective = None
            if recovered.status is DddPrimalRecoveryStatus.FEASIBLE:
                if recovered.schedule is None:
                    raise RuntimeError("feasible DDD recovery returned no schedule")
                validate_ddd_recovered_schedule(
                    current,
                    recovered.schedule,
                    tolerance_seconds=self.tolerance_seconds,
                )
                recovery_objective = recovered.schedule.objective_value
                if recovery_objective < upper_bound:
                    upper_bound = recovery_objective
                    best_schedule = recovered.schedule

            strict = lifter.lift(current, path)
            if strict.status is DddStrictTimeLiftStatus.FEASIBLE:
                if strict.schedule is None:
                    raise RuntimeError("feasible DDD strict lift returned no schedule")
                if strict.schedule.objective_value < upper_bound:
                    upper_bound = strict.schedule.objective_value
                    best_schedule = strict.schedule

            if lower_bound > upper_bound + self.bound_tolerance:
                iterations.append(
                    _iteration(
                        round_index=round_index,
                        problem=current,
                        candidate_path_count=master_result.candidate_path_count,
                        path=path,
                        master_bound=master_bound,
                        lower_bound=lower_bound,
                        strict_status=strict.status,
                        recovery_status=recovered.status,
                        recovery_objective=recovery_objective,
                        upper_bound=upper_bound,
                        inconsistency=strict.inconsistency,
                    )
                )
                return _result(
                    status=DddTimeRefinementStatus.INVALID_INTERNAL,
                    solution=best_schedule,
                    lower_bound=lower_bound,
                    upper_bound=upper_bound,
                    iterations=iterations,
                    discretization=current.discretization,
                )

            iterations.append(
                _iteration(
                    round_index=round_index,
                    problem=current,
                    candidate_path_count=master_result.candidate_path_count,
                    path=path,
                    master_bound=master_bound,
                    lower_bound=lower_bound,
                    strict_status=strict.status,
                    recovery_status=recovered.status,
                    recovery_objective=recovery_objective,
                    upper_bound=upper_bound,
                    inconsistency=strict.inconsistency,
                )
            )
            if upper_bound - lower_bound <= self.bound_tolerance:
                return _result(
                    status=DddTimeRefinementStatus.OPTIMAL,
                    solution=best_schedule,
                    lower_bound=lower_bound,
                    upper_bound=upper_bound,
                    iterations=iterations,
                    discretization=current.discretization,
                )
            if strict.inconsistency is None:
                raise RuntimeError(
                    "DDD strict lift neither closed the gap nor produced refinement"
                )
            refined = current.discretization.split(
                state_id=strict.inconsistency.state_id,
                boundary_seconds=strict.inconsistency.split_boundary_seconds,
                tolerance_seconds=self.tolerance_seconds,
            )
            current = current.with_discretization(refined)

        status = (
            DddTimeRefinementStatus.FEASIBLE_WITH_GAP
            if best_schedule is not None
            else DddTimeRefinementStatus.UNKNOWN_NO_INCUMBENT
        )
        return _result(
            status=status,
            solution=best_schedule,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            iterations=iterations,
            discretization=current.discretization,
        )


def _iteration(
    *,
    round_index: int,
    problem: DddPartialTimeProblem,
    candidate_path_count: int,
    path: DddPartialTimedPath,
    master_bound: float,
    lower_bound: float,
    strict_status: DddStrictTimeLiftStatus,
    recovery_status: DddPrimalRecoveryStatus,
    recovery_objective: float | None,
    upper_bound: float,
    inconsistency: DddEventCellInconsistency | None,
) -> DddTimeRefinementIteration:
    return DddTimeRefinementIteration(
        round_index=round_index,
        discretization_fingerprint=problem.discretization.fingerprint,
        candidate_path_count=candidate_path_count,
        selected_path_fingerprint=path.fingerprint,
        master_lower_bound=master_bound,
        global_lower_bound=_finite_or_none(lower_bound),
        strict_lift_status=strict_status,
        recovery_status=recovery_status,
        recovery_objective=recovery_objective,
        global_upper_bound=_finite_or_none(upper_bound),
        split_state_id=(inconsistency.state_id if inconsistency else None),
        split_boundary_seconds=(
            inconsistency.split_boundary_seconds if inconsistency else None
        ),
    )


def _result(
    *,
    status: DddTimeRefinementStatus,
    solution: DddRecoveredSchedule | None,
    lower_bound: float,
    upper_bound: float,
    iterations: list[DddTimeRefinementIteration],
    discretization: DddTimeDiscretization,
) -> DddTimeRefinementResult:
    finite_lower = _finite_or_none(lower_bound)
    finite_upper = _finite_or_none(upper_bound)
    gap = (
        max(0.0, finite_upper - finite_lower)
        if finite_lower is not None and finite_upper is not None
        else None
    )
    return DddTimeRefinementResult(
        status=status,
        solution=solution,
        global_lower_bound=finite_lower,
        global_upper_bound=finite_upper,
        absolute_gap=gap,
        iterations=tuple(iterations),
        final_discretization=discretization,
    )


def _finite_or_none(value: float) -> float | None:
    return value if math.isfinite(value) else None
