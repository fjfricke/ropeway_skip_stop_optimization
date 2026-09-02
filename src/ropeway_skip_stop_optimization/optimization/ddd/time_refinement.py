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
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    DddTimeTick,
    ddd_quantize_time_seconds,
    ddd_seconds_to_tick,
    ddd_tick_to_seconds,
)
from ropeway_skip_stop_optimization.optimization.ddd.models import DddRouteDecision


@dataclass(frozen=True)
class DddExactTimedEvent:
    event_index: int
    state_id: str
    time_seconds: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "time_seconds",
            ddd_quantize_time_seconds(self.time_seconds),
        )

    @property
    def time_tick(self) -> DddTimeTick:
        return ddd_seconds_to_tick(self.time_seconds)


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
    if (
        first.event_index != 0
        or first.state_id != start.state_id
        or first.time_tick != start.time_tick
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
        if (
            source.state_id != option.from_state_id
            or target.state_id != option.to_state_id
        ):
            raise ValueError("DDD recovered route chain is inconsistent")
        if source.time_tick > problem.movement_problem.operational_end_tick:
            raise ValueError("DDD recovered route departs after operational horizon")
        wait_tick = target.time_tick - source.time_tick - option.duration_tick
        if wait_tick < 0:
            raise ValueError("DDD recovered route duration is inconsistent")
        allowed_wait_ticks = {
            ddd_seconds_to_tick(value)
            for value in problem.waiting_policy.wait_values_seconds(
                option.station_id
            )
        }
        if wait_tick not in allowed_wait_ticks:
            raise ValueError("DDD recovered wait lies outside the configured domain")
        if option.decision is DddRouteDecision.SKIP and wait_tick:
            raise ValueError("DDD recovered SKIP route cannot wait")
        if wait_tick:
            if option.platform_exit_offset_seconds is None:
                raise ValueError("DDD recovered waiting route lacks a platform exit")
            if (
                source.time_tick
                + ddd_seconds_to_tick(option.platform_exit_offset_seconds)
                < ddd_seconds_to_tick(
                    problem.waiting_policy.earliest_wait_time_seconds
                )
            ):
                raise ValueError("DDD recovered route waits before the boundary")
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


class DddTimeRefinementStalledError(ValueError):
    """An inconsistency is proved but no tolerance-safe split is available."""


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
    inconsistencies: tuple[DddEventCellInconsistency, ...] = ()

    @property
    def inconsistency(self) -> DddEventCellInconsistency | None:
        """Return the first inconsistency for legacy single-split callers."""

        return self.inconsistencies[0] if self.inconsistencies else None


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
        inconsistencies: list[DddEventCellInconsistency] = []
        for arc_index, (arc, source_event, target_event) in enumerate(
            zip(
                path.arcs,
                schedule.events[:-1],
                schedule.events[1:],
                strict=True,
            )
        ):
            if arc.source_cell_id is not None:
                if arc_index == 0:
                    raise ValueError(
                        "DDD first strict-lift arc cannot reference a source cell"
                    )
                selected_source_cell = path.arcs[arc_index - 1].target_cell
                if selected_source_cell.id != arc.source_cell_id:
                    raise ValueError("DDD strict lift source-cell chain is broken")
                source_cell_is_exact = selected_source_cell.contains_tick(
                    source_event.time_tick
                )
                if (
                    source_cell_is_exact
                    and source_event.time_tick
                    > problem.movement_problem.operational_end_tick
                ):
                    split_tick = source_event.time_tick
                    split_boundary = ddd_tick_to_seconds(split_tick)
                    if not (
                        selected_source_cell.lower_tick
                        < split_tick
                        < selected_source_cell.upper_tick
                    ):
                        continue
                    inconsistencies.append(
                        DddEventCellInconsistency(
                            state_id=arc.from_state_id,
                            selected_cell_id=selected_source_cell.id,
                            exact_source_time_seconds=source_event.time_seconds,
                            required_source_lower_seconds=(
                                problem.movement_problem.operational_end_seconds
                            ),
                            required_source_upper_seconds=split_boundary,
                            split_boundary_seconds=split_boundary,
                            failed_target_cell_id=arc.target_cell.id,
                        )
                    )
            if arc.target_cell.contains_tick(target_event.time_tick):
                continue
            inconsistency = _build_back_propagated_inconsistency(
                problem=problem,
                path=path,
                schedule=schedule,
                failed_arc_index=arc_index,
            )
            if inconsistency is None:
                raise DddTimeRefinementStalledError(
                    "DDD event-cell inconsistency has no earlier consistent "
                    f"cell with an interior boundary: target={arc.target_cell.id}, "
                    f"exact={target_event.time_seconds}"
                )
            inconsistencies.append(inconsistency)

        if inconsistencies:
            unique = tuple(dict.fromkeys(inconsistencies))
            return DddStrictTimeLiftResult(
                status=DddStrictTimeLiftStatus.EVENT_CELL_INCONSISTENCY,
                schedule=None,
                inconsistencies=unique,
            )

        validate_ddd_recovered_schedule(
            problem,
            schedule,
            tolerance_seconds=self.tolerance_seconds,
        )
        return DddStrictTimeLiftResult(
            status=DddStrictTimeLiftStatus.FEASIBLE,
            schedule=schedule,
        )


def _build_back_propagated_inconsistency(
    *,
    problem: DddPartialTimeProblem,
    path: DddPartialTimedPath,
    schedule: DddRecoveredSchedule,
    failed_arc_index: int,
) -> DddEventCellInconsistency | None:
    """Project a failed target cell to the latest exact-consistent earlier cell."""

    failed_arc = path.arcs[failed_arc_index]
    target_event = schedule.events[failed_arc_index + 1]
    for anchor_event_index in range(failed_arc_index, 0, -1):
        anchor_cell = path.arcs[anchor_event_index - 1].target_cell
        anchor_event = schedule.events[anchor_event_index]
        if not anchor_cell.contains_tick(anchor_event.time_tick):
            continue
        elapsed_tick = target_event.time_tick - anchor_event.time_tick
        required_lower_tick = failed_arc.target_cell.lower_tick - elapsed_tick
        required_upper_tick = failed_arc.target_cell.upper_tick - elapsed_tick
        split_tick = (
            required_lower_tick
            if anchor_event.time_tick < required_lower_tick
            else required_upper_tick
        )
        if not anchor_cell.lower_tick < split_tick < anchor_cell.upper_tick:
            continue
        return DddEventCellInconsistency(
            state_id=anchor_event.state_id,
            selected_cell_id=anchor_cell.id,
            exact_source_time_seconds=anchor_event.time_seconds,
            required_source_lower_seconds=ddd_tick_to_seconds(required_lower_tick),
            required_source_upper_seconds=ddd_tick_to_seconds(required_upper_tick),
            split_boundary_seconds=ddd_tick_to_seconds(split_tick),
            failed_target_cell_id=failed_arc.target_cell.id,
        )
    return None


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
    time_tick = start.time_tick
    for index, (option_id, partial_arc) in enumerate(
        zip(path.route_option_ids, path.arcs, strict=True)
    ):
        option = options_by_id.get(option_id)
        if option is None or option.from_state_id != state_id:
            raise ValueError("DDD partial path route support is inconsistent")
        time_tick += option.duration_tick + partial_arc.minimum_wait_tick
        state_id = option.to_state_id
        events.append(
            DddExactTimedEvent(
                index + 1,
                state_id,
                ddd_tick_to_seconds(time_tick),
            )
        )
    objective_value = problem.objective.exact_value(
        path.route_option_ids,
        ddd_tick_to_seconds(time_tick),
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
        recovery = DddCellFreeSupportRecovery(tolerance_seconds=self.tolerance_seconds)
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
                raise RuntimeError(
                    "optimal DDD partial master returned no path or bound"
                )
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
