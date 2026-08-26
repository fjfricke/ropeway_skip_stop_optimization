from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter
from typing import Callable

from ortools.sat.python import cp_model

from ropeway_skip_stop_optimization.optimization.ddd.aggregate_support import (
    DddAggregateRouteCountLiteral,
    DddCpSatFixedSupport,
)
from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddMovementProblem,
    DddRouteDecision,
    DddRouteOption,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceResourceOccurrence,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddNetworkTimeProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.support_master import (
    DddSupportLiteral,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_refinement import (
    DddExactTimedEvent,
    DddRecoveredSchedule,
)
from ropeway_skip_stop_optimization.optimization.ddd.timed_flow_cover import (
    DddCpSatTimedFlowSupport,
    DddTimedFlowThresholdLiteral,
    DddTimedFlowTimingScope,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_space import (
    DddPartialTimedPath,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    DDD_TIME_TICKS_PER_SECOND,
    ddd_seconds_to_tick,
    ddd_tick_to_seconds,
)


class DddCpSatPrimalStatus(StrEnum):
    NOT_RUN = "not_run"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    EXHAUSTED = "exhausted"
    UNKNOWN = "unknown"


class DddCpSatPassengerObjectiveEvent(StrEnum):
    BOARDING = "boarding"
    ALIGHTING = "alighting"


@dataclass(frozen=True)
class DddCpSatPassengerRidePreference:
    """One dual-adjusted direct-ride opportunity used only for primal search."""

    id: str
    cabin_id: int
    board_visit_index: int
    alight_visit_index: int
    release_tick: int
    board_offset_tick: int
    alight_offset_tick: int
    service_horizon_tick: int
    demand_dual_tick: int
    passenger_weight: int
    objective_event: DddCpSatPassengerObjectiveEvent

    def validate(self) -> None:
        if not self.id:
            raise ValueError("CP-SAT Passenger pricing preference ID must not be empty")
        if self.cabin_id < 0:
            raise ValueError("CP-SAT Passenger pricing cabin ID must be nonnegative")
        if (
            self.board_visit_index < 0
            or self.alight_visit_index <= self.board_visit_index
        ):
            raise ValueError("CP-SAT Passenger pricing visits are invalid")
        if (
            min(
                self.release_tick,
                self.board_offset_tick,
                self.alight_offset_tick,
                self.service_horizon_tick,
            )
            < 0
        ):
            raise ValueError("CP-SAT Passenger pricing times must be nonnegative")
        if self.passenger_weight <= 0:
            raise ValueError("CP-SAT Passenger pricing weight must be positive")
        if not isinstance(self.objective_event, DddCpSatPassengerObjectiveEvent):
            raise ValueError("CP-SAT Passenger pricing objective event is invalid")


@dataclass(frozen=True)
class DddCpSatPrimalResult:
    status: DddCpSatPrimalStatus
    schedules: tuple[DddRecoveredSchedule, ...]
    wall_seconds: float
    conflict_count: int
    branch_count: int
    candidate_schedules: tuple[tuple[DddRecoveredSchedule, ...], ...] = ()
    search_complete: bool = False
    fixed_support: DddCpSatFixedSupport | None = None
    infeasible_core: tuple[DddAggregateRouteCountLiteral, ...] = ()
    timed_flow_support: DddCpSatTimedFlowSupport | None = None
    timed_flow_infeasible_core: tuple[DddTimedFlowThresholdLiteral, ...] = ()
    fixed_cabin_paths: tuple[DddPartialTimedPath, ...] = ()
    cabin_path_infeasible_core: tuple[DddSupportLiteral, ...] = ()
    distance_center: tuple[DddAggregateRouteCountLiteral, ...] = ()
    support_distance_primal: int | None = None
    support_distance_lower_bound: float | None = None
    passenger_pricing_preference_count: int = 0
    passenger_pricing_objective_value: float | None = None
    passenger_pricing_objective_bound: float | None = None
    solver_status_name: str = "NOT_RUN"
    solver_response_stats: str | None = None


DddCpSatCandidateCallback = Callable[[int, float], None]


@dataclass(frozen=True)
class DddCpSatPrimalOracle:
    """Exact fixed-start movement scheduler over all deterministic route choices.

    Version one uses zero waiting. The formulation already separates route
    selection, integer event times, and optional resource intervals so bounded
    waiting can later enter through the transition and occurrence expressions
    without changing the master/oracle contract.
    """

    time_limit_seconds: float = 2.0
    num_workers: int = 8
    log_search_progress: bool = False
    max_candidate_count: int = 1
    minimum_hamming_distance: int = 1

    def solve(
        self,
        problem: DddNetworkTimeProblem,
        *,
        hint_paths: tuple[DddPartialTimedPath, ...] = (),
        hint_schedules: tuple[DddRecoveredSchedule, ...] = (),
        fixed_support: DddCpSatFixedSupport | None = None,
        timed_flow_support: DddCpSatTimedFlowSupport | None = None,
        nearest_support: DddCpSatFixedSupport | None = None,
        fixed_cabin_paths: tuple[DddPartialTimedPath, ...] = (),
        enabled_resource_ids: tuple[str, ...] | None = None,
        excluded_schedules: tuple[tuple[DddRecoveredSchedule, ...], ...] = (),
        passenger_ride_preferences: tuple[DddCpSatPassengerRidePreference, ...] = (),
        candidate_callback: DddCpSatCandidateCallback | None = None,
        boundary_occurrences: tuple[DddReferenceResourceOccurrence, ...] = (),
    ) -> DddCpSatPrimalResult:
        problem.validate()
        if fixed_support is not None:
            fixed_support.validate()
        if nearest_support is not None:
            nearest_support.validate()
        if timed_flow_support is not None:
            timed_flow_support.validate()
            if any(
                item.region.timing_scope is not DddTimedFlowTimingScope.NO_WAIT
                for item in timed_flow_support.arc_flows
            ):
                raise ValueError(
                    "DDD CP-SAT v1 only supports no-wait timed-flow proofs"
                )
        _validate_fixed_cabin_paths(problem, fixed_cabin_paths)
        _validate_excluded_schedules(problem, excluded_schedules)
        for preference in passenger_ride_preferences:
            preference.validate()
        selected_support_modes = sum(
            item
            for item in (
                fixed_support is not None,
                timed_flow_support is not None,
                nearest_support is not None,
                bool(fixed_cabin_paths),
            )
        )
        if selected_support_modes > 1:
            raise ValueError(
                "fixed aggregate, timed-flow, nearest, and fixed cabin-path "
                "CP-SAT support are mutually exclusive"
            )
        if passenger_ride_preferences and nearest_support is not None:
            raise ValueError(
                "Passenger pricing and nearest-support objectives are mutually exclusive"
            )
        if self.time_limit_seconds <= 0:
            raise ValueError("DDD CP-SAT time limit must be positive")
        if self.num_workers <= 0:
            raise ValueError("DDD CP-SAT worker count must be positive")
        if self.max_candidate_count <= 0:
            raise ValueError("DDD CP-SAT candidate count must be positive")
        if self.minimum_hamming_distance <= 0:
            raise ValueError("DDD CP-SAT Hamming distance must be positive")

        started = perf_counter()
        movement = problem.movement_problem
        if enabled_resource_ids is not None:
            if not enabled_resource_ids:
                raise ValueError("DDD CP-SAT enabled resource set must not be empty")
            if tuple(sorted(set(enabled_resource_ids))) != enabled_resource_ids:
                raise ValueError(
                    "DDD CP-SAT enabled resource ids must be sorted and unique"
                )
            unknown_resource_ids = (
                set(enabled_resource_ids) - movement.resources_by_id.keys()
            )
            if unknown_resource_ids:
                raise ValueError(
                    "DDD CP-SAT enabled resource ids are unknown: "
                    f"{sorted(unknown_resource_ids)}"
                )
        enabled_resource_id_set = (
            None if enabled_resource_ids is None else set(enabled_resource_ids)
        )
        model = cp_model.CpModel()
        max_completion_tick = movement.operational_end_tick + max(
            option.duration_tick for option in movement.route_options
        )
        hint_by_cabin = {path.cabin_id: path for path in hint_schedules}
        hint_by_cabin.update({path.cabin_id: path for path in hint_paths})
        time_by_cabin: dict[int, list[cp_model.IntVar]] = {}
        active_by_cabin: dict[int, list[cp_model.IntVar]] = {}
        selection_by_key: dict[tuple[int, int, str], cp_model.IntVar] = {}
        states_by_cabin: dict[int, tuple[str, ...]] = {}
        resource_intervals: dict[str, list[cp_model.IntervalVar]] = {
            resource.id: []
            for resource in movement.resources
            if enabled_resource_id_set is None or resource.id in enabled_resource_id_set
        }
        for index, occurrence in enumerate(boundary_occurrences):
            resource = movement.resources_by_id.get(occurrence.resource_id)
            if resource is None:
                raise ValueError("CP-SAT boundary occurrence uses an unknown resource")
            if (
                enabled_resource_id_set is not None
                and occurrence.resource_id not in enabled_resource_id_set
            ):
                continue
            end_tick = ddd_seconds_to_tick(
                occurrence.leader_clear_time_seconds
            ) + occurrence.separation_after_tick(resource)
            start_tick = max(
                0,
                ddd_seconds_to_tick(occurrence.follower_enter_time_seconds),
            )
            if end_tick <= start_tick:
                continue
            resource_intervals[occurrence.resource_id].append(
                model.new_fixed_size_interval_var(
                    start_tick,
                    end_tick - start_tick,
                    f"boundary[{index}]",
                )
            )

        for start in sorted(movement.starts, key=lambda item: item.cabin_id):
            states, options_by_visit = _deterministic_visit_structure(
                movement,
                start.state_id,
                start.max_visit_count,
            )
            states_by_cabin[start.cabin_id] = states
            event_times = [
                model.new_int_var(
                    start.time_tick if visit_index == 0 else 0,
                    start.time_tick if visit_index == 0 else max_completion_tick,
                    f"time[{start.cabin_id},{visit_index}]",
                )
                for visit_index in range(start.max_visit_count + 1)
            ]
            active = [
                model.new_bool_var(f"active[{start.cabin_id},{visit_index}]")
                for visit_index in range(start.max_visit_count + 1)
            ]
            model.add(active[0] == 1)
            model.add(active[-1] == 0)
            for visit_index in range(start.max_visit_count + 1):
                model.add(
                    event_times[visit_index] <= movement.operational_end_tick
                ).only_enforce_if(active[visit_index])
                model.add(
                    event_times[visit_index] >= movement.operational_end_tick + 1
                ).only_enforce_if(active[visit_index].Not())

            hinted_route_ids = (
                hint_by_cabin[start.cabin_id].route_option_ids
                if start.cabin_id in hint_by_cabin
                else ()
            )
            for visit_index, options in enumerate(options_by_visit):
                selections = []
                for option in options:
                    selected = model.new_bool_var(
                        f"route[{start.cabin_id},{visit_index},{option.id}]"
                    )
                    selection_by_key[(start.cabin_id, visit_index, option.id)] = (
                        selected
                    )
                    selections.append(selected)
                    if visit_index < len(hinted_route_ids):
                        model.add_hint(
                            selected,
                            int(hinted_route_ids[visit_index] == option.id),
                        )
                    _add_resource_intervals(
                        model=model,
                        movement=movement,
                        cabin_id=start.cabin_id,
                        visit_index=visit_index,
                        event_time=event_times[visit_index],
                        selected=selected,
                        option=option,
                        intervals_by_resource=resource_intervals,
                    )
                model.add(sum(selections) == active[visit_index])
                model.add(
                    event_times[visit_index + 1]
                    == event_times[visit_index]
                    + sum(
                        option.duration_tick
                        * selection_by_key[(start.cabin_id, visit_index, option.id)]
                        for option in options
                    )
                )

            time_by_cabin[start.cabin_id] = event_times
            active_by_cabin[start.cabin_id] = active

        for intervals in resource_intervals.values():
            if intervals:
                model.add_no_overlap(intervals)

        passenger_pricing_expression = None
        if passenger_ride_preferences:
            passenger_pricing_expression = _add_passenger_pricing_objective(
                model=model,
                movement=movement,
                preferences=passenger_ride_preferences,
                states_by_cabin=states_by_cabin,
                time_by_cabin=time_by_cabin,
                selection_by_key=selection_by_key,
                max_completion_tick=max_completion_tick,
            )

        assumption_literal_by_index: dict[int, DddAggregateRouteCountLiteral] = {}
        if fixed_support is not None:
            assumption_literal_by_index = _fix_aggregate_route_support(
                model=model,
                selection_by_key=selection_by_key,
                fixed_support=fixed_support,
            )
        timed_flow_literal_by_index: dict[int, DddTimedFlowThresholdLiteral] = {}
        if timed_flow_support is not None:
            timed_flow_literal_by_index = _fix_timed_flow_support(
                model=model,
                selection_by_key=selection_by_key,
                time_by_cabin=time_by_cabin,
                timed_flow_support=timed_flow_support,
            )
        cabin_path_literal_by_assumption_index: dict[int, DddSupportLiteral] = {}
        if fixed_cabin_paths:
            cabin_path_literal_by_assumption_index = _fix_cabin_route_prefixes(
                model=model,
                selection_by_key=selection_by_key,
                fixed_cabin_paths=fixed_cabin_paths,
            )
        _exclude_route_patterns(
            model=model,
            selection_by_key=selection_by_key,
            excluded_schedules=excluded_schedules,
            minimum_hamming_distance=self.minimum_hamming_distance,
        )

        distance_center: tuple[DddAggregateRouteCountLiteral, ...] = ()
        if nearest_support is not None:
            distance_center, distance_expression = _add_nearest_support_objective(
                model=model,
                selection_by_key=selection_by_key,
                nearest_support=nearest_support,
            )
            model.minimize(distance_expression)
        elif passenger_pricing_expression is not None:
            model.minimize(passenger_pricing_expression)

        candidate_schedules: list[tuple[DddRecoveredSchedule, ...]] = []
        conflict_count = 0
        branch_count = 0
        search_complete = False
        terminal_status = cp_model.UNKNOWN
        last_solver: cp_model.CpSolver | None = None
        candidate_limit = 1 if nearest_support is not None else self.max_candidate_count
        last_feasible_solver: cp_model.CpSolver | None = None
        while len(candidate_schedules) < candidate_limit:
            remaining_seconds = self.time_limit_seconds - (perf_counter() - started)
            if remaining_seconds <= 0:
                terminal_status = cp_model.UNKNOWN
                break
            solver = cp_model.CpSolver()
            last_solver = solver
            solver.parameters.max_time_in_seconds = remaining_seconds
            solver.parameters.num_search_workers = self.num_workers
            solver.parameters.log_search_progress = self.log_search_progress
            solver.parameters.random_seed = 0
            solver.parameters.stop_after_first_solution = (
                nearest_support is None and not passenger_ride_preferences
            )
            terminal_status = solver.solve(model)
            conflict_count += solver.num_conflicts
            branch_count += solver.num_branches
            if terminal_status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
                search_complete = (
                    terminal_status == cp_model.INFEASIBLE
                    and self.minimum_hamming_distance == 1
                )
                break
            last_feasible_solver = solver
            schedules = _extract_schedules(
                problem=problem,
                solver=solver,
                states_by_cabin=states_by_cabin,
                time_by_cabin=time_by_cabin,
                active_by_cabin=active_by_cabin,
                selection_by_key=selection_by_key,
            )
            candidate_schedules.append(schedules)
            if candidate_callback is not None:
                candidate_callback(
                    len(candidate_schedules),
                    perf_counter() - started,
                )
            if nearest_support is not None:
                search_complete = terminal_status == cp_model.OPTIMAL
                break
            _exclude_solution_and_replace_hint(
                model=model,
                solver=solver,
                selection_by_key=selection_by_key,
                time_by_cabin=time_by_cabin,
                active_by_cabin=active_by_cabin,
                minimum_hamming_distance=self.minimum_hamming_distance,
            )
        wall_seconds = perf_counter() - started
        infeasible_core: tuple[DddAggregateRouteCountLiteral, ...] = ()
        timed_flow_infeasible_core: tuple[DddTimedFlowThresholdLiteral, ...] = ()
        cabin_path_infeasible_core: tuple[DddSupportLiteral, ...] = ()
        support_distance_primal: int | None = None
        support_distance_lower_bound: float | None = None
        passenger_pricing_objective_value: float | None = None
        passenger_pricing_objective_bound: float | None = None
        if candidate_schedules:
            schedules = candidate_schedules[0]
            result_status = DddCpSatPrimalStatus.FEASIBLE
            if nearest_support is not None:
                if last_feasible_solver is None:
                    raise RuntimeError("nearest-support CP-SAT solve has no solver")
                support_distance_primal = int(
                    round(last_feasible_solver.objective_value)
                )
                support_distance_lower_bound = float(
                    last_feasible_solver.best_objective_bound
                )
            elif passenger_ride_preferences:
                if last_feasible_solver is None:
                    raise RuntimeError("Passenger pricing solve has no solver")
                passenger_pricing_objective_value = float(
                    last_feasible_solver.objective_value / DDD_TIME_TICKS_PER_SECOND
                )
                passenger_pricing_objective_bound = float(
                    last_feasible_solver.best_objective_bound
                    / DDD_TIME_TICKS_PER_SECOND
                )
        elif terminal_status == cp_model.INFEASIBLE and excluded_schedules:
            schedules = ()
            result_status = DddCpSatPrimalStatus.EXHAUSTED
        elif terminal_status == cp_model.INFEASIBLE:
            schedules = ()
            result_status = DddCpSatPrimalStatus.INFEASIBLE
            if fixed_support is not None:
                core_indices = solver.sufficient_assumptions_for_infeasibility()
                infeasible_core = tuple(
                    sorted(assumption_literal_by_index[index] for index in core_indices)
                )
            elif timed_flow_support is not None:
                core_indices = solver.sufficient_assumptions_for_infeasibility()
                timed_flow_infeasible_core = tuple(
                    sorted(
                        (timed_flow_literal_by_index[index] for index in core_indices),
                        key=lambda item: item.sort_key,
                    )
                )
            elif fixed_cabin_paths:
                core_indices = solver.sufficient_assumptions_for_infeasibility()
                cabin_path_infeasible_core = tuple(
                    sorted(
                        cabin_path_literal_by_assumption_index[index]
                        for index in core_indices
                    )
                )
        else:
            schedules = ()
            result_status = DddCpSatPrimalStatus.UNKNOWN
        return DddCpSatPrimalResult(
            status=result_status,
            schedules=schedules,
            wall_seconds=wall_seconds,
            conflict_count=conflict_count,
            branch_count=branch_count,
            candidate_schedules=tuple(candidate_schedules),
            search_complete=search_complete,
            fixed_support=fixed_support,
            infeasible_core=infeasible_core,
            timed_flow_support=timed_flow_support,
            timed_flow_infeasible_core=timed_flow_infeasible_core,
            fixed_cabin_paths=fixed_cabin_paths,
            cabin_path_infeasible_core=cabin_path_infeasible_core,
            distance_center=distance_center,
            support_distance_primal=support_distance_primal,
            support_distance_lower_bound=support_distance_lower_bound,
            passenger_pricing_preference_count=len(passenger_ride_preferences),
            passenger_pricing_objective_value=passenger_pricing_objective_value,
            passenger_pricing_objective_bound=passenger_pricing_objective_bound,
            solver_status_name=(
                "UNKNOWN"
                if last_solver is None
                else last_solver.status_name(terminal_status)
            ),
            solver_response_stats=(
                None if last_solver is None else last_solver.response_stats()
            ),
        )


def _add_passenger_pricing_objective(
    *,
    model: cp_model.CpModel,
    movement: DddMovementProblem,
    preferences: tuple[DddCpSatPassengerRidePreference, ...],
    states_by_cabin: dict[int, tuple[str, ...]],
    time_by_cabin: dict[int, list[cp_model.IntVar]],
    selection_by_key: dict[tuple[int, int, str], cp_model.IntVar],
    max_completion_tick: int,
) -> cp_model.LinearExpr:
    options_by_state = movement.route_options_by_state_id
    terms = []
    seen_ids: set[str] = set()
    for index, preference in enumerate(preferences):
        if preference.id in seen_ids:
            raise ValueError("CP-SAT Passenger pricing preference IDs must be unique")
        seen_ids.add(preference.id)
        if preference.cabin_id not in states_by_cabin:
            raise ValueError("CP-SAT Passenger pricing references an unknown cabin")
        states = states_by_cabin[preference.cabin_id]
        if preference.alight_visit_index >= len(states) - 1:
            raise ValueError("CP-SAT Passenger pricing visit exceeds cabin horizon")

        def stop_literal(visit_index: int) -> cp_model.IntVar:
            state_id = states[visit_index]
            stop_selections = tuple(
                selection_by_key[preference.cabin_id, visit_index, option.id]
                for option in options_by_state[state_id]
                if option.decision is DddRouteDecision.STOP
            )
            if not stop_selections:
                raise ValueError("CP-SAT Passenger pricing visit has no STOP option")
            if len(stop_selections) == 1:
                return stop_selections[0]
            result = model.new_bool_var(f"pricing_stop[{index},{visit_index}]")
            model.add(result == sum(stop_selections))
            return result

        board_stop = stop_literal(preference.board_visit_index)
        alight_stop = stop_literal(preference.alight_visit_index)
        board_time = (
            time_by_cabin[preference.cabin_id][preference.board_visit_index]
            + preference.board_offset_tick
        )
        alight_time = (
            time_by_cabin[preference.cabin_id][preference.alight_visit_index]
            + preference.alight_offset_tick
        )
        released = model.new_bool_var(f"pricing_released[{index}]")
        model.add(board_time >= preference.release_tick).only_enforce_if(released)
        model.add(board_time <= preference.release_tick - 1).only_enforce_if(
            released.Not()
        )
        board_in_horizon = model.new_bool_var(f"pricing_board_horizon[{index}]")
        model.add(board_time <= preference.service_horizon_tick).only_enforce_if(
            board_in_horizon
        )
        model.add(board_time >= preference.service_horizon_tick + 1).only_enforce_if(
            board_in_horizon.Not()
        )
        alight_in_horizon = model.new_bool_var(f"pricing_alight_horizon[{index}]")
        model.add(alight_time <= preference.service_horizon_tick).only_enforce_if(
            alight_in_horizon
        )
        model.add(alight_time >= preference.service_horizon_tick + 1).only_enforce_if(
            alight_in_horizon.Not()
        )
        available = model.new_bool_var(f"pricing_available[{index}]")
        requirements = (
            board_stop,
            alight_stop,
            released,
            board_in_horizon,
            alight_in_horizon,
        )
        for requirement in requirements:
            model.add(available <= requirement)
        model.add(available >= sum(requirements) - (len(requirements) - 1))

        event_time = (
            board_time
            if preference.objective_event is DddCpSatPassengerObjectiveEvent.BOARDING
            else alight_time
        )
        maximum_event_tick = max_completion_tick + max(
            preference.board_offset_tick,
            preference.alight_offset_tick,
        )
        active_event_time = model.new_int_var(
            0,
            maximum_event_tick,
            f"pricing_event[{index}]",
        )
        model.add_multiplication_equality(active_event_time, [event_time, available])
        adjusted_horizon_tick = (
            preference.service_horizon_tick + preference.demand_dual_tick
        )
        terms.append(
            preference.passenger_weight
            * (active_event_time - adjusted_horizon_tick * available)
        )
    return sum(terms)


def _validate_fixed_cabin_paths(
    problem: DddNetworkTimeProblem,
    fixed_cabin_paths: tuple[DddPartialTimedPath, ...],
) -> None:
    if not fixed_cabin_paths:
        return
    known_cabin_ids = {start.cabin_id for start in problem.movement_problem.starts}
    cabin_ids = tuple(path.cabin_id for path in fixed_cabin_paths)
    if len(set(cabin_ids)) != len(cabin_ids):
        raise ValueError("DDD fixed cabin paths must have unique cabin ids")
    unknown_cabin_ids = set(cabin_ids) - known_cabin_ids
    if unknown_cabin_ids:
        raise ValueError(
            "DDD fixed cabin paths reference unknown cabins: "
            f"{sorted(unknown_cabin_ids)}"
        )
    for path in fixed_cabin_paths:
        if not path.arcs:
            raise ValueError("DDD fixed cabin path must contain at least one route")
        if any(
            arc.visit_index != visit_index for visit_index, arc in enumerate(path.arcs)
        ):
            raise ValueError(
                f"DDD fixed cabin path {path.cabin_id} is not a complete prefix"
            )


def _fix_cabin_route_prefixes(
    *,
    model: cp_model.CpModel,
    selection_by_key: dict[tuple[int, int, str], cp_model.IntVar],
    fixed_cabin_paths: tuple[DddPartialTimedPath, ...],
) -> dict[int, DddSupportLiteral]:
    """Add one assumption for every route literal in the cabin paths.

    A literal-level infeasibility core identifies the deepest relevant visit
    per cabin.  The master retains the raw no-good while labelled-flow
    conservation supplies identity from the fixed start through that depth.
    """

    literal_by_index: dict[int, DddSupportLiteral] = {}
    for path in sorted(fixed_cabin_paths, key=lambda item: item.cabin_id):
        for visit_index, route_option_id in enumerate(path.route_option_ids):
            assumption = model.new_bool_var(
                f"cabin_path_assumption[{path.cabin_id},{visit_index}]"
            )
            selected = selection_by_key.get(
                (path.cabin_id, visit_index, route_option_id)
            )
            if selected is None:
                model.add(0 == 1).only_enforce_if(assumption)
            else:
                model.add(selected == 1).only_enforce_if(assumption)
            model.add_assumption(assumption)
            literal_by_index[assumption.Index()] = DddSupportLiteral(
                cabin_id=path.cabin_id,
                visit_index=visit_index,
                route_option_id=route_option_id,
            )
    return literal_by_index


def _fix_timed_flow_support(
    *,
    model: cp_model.CpModel,
    selection_by_key: dict[tuple[int, int, str], cp_model.IntVar],
    time_by_cabin: dict[int, list[cp_model.IntVar]],
    timed_flow_support: DddCpSatTimedFlowSupport,
) -> dict[int, DddTimedFlowThresholdLiteral]:
    """Condition lower bounds on exact CP traversals of stable timed regions."""

    comparison_cache: dict[tuple[int, str, int], cp_model.IntVar] = {}

    def comparison(
        variable: cp_model.IntVar,
        *,
        sense: str,
        bound: int,
    ) -> cp_model.IntVar:
        key = (variable.Index(), sense, bound)
        known = comparison_cache.get(key)
        if known is not None:
            return known
        result = model.new_bool_var(f"timed_flow_{sense}[{variable.Index()},{bound}]")
        if sense == "ge":
            model.add(variable >= bound).only_enforce_if(result)
            model.add(variable <= bound - 1).only_enforce_if(result.Not())
        elif sense == "lt":
            model.add(variable <= bound - 1).only_enforce_if(result)
            model.add(variable >= bound).only_enforce_if(result.Not())
        else:
            raise ValueError(f"unsupported DDD timed-flow comparison: {sense}")
        comparison_cache[key] = result
        return result

    literal_by_index: dict[int, DddTimedFlowThresholdLiteral] = {}
    for support_index, item in enumerate(timed_flow_support.arc_flows):
        region = item.region
        presences: list[cp_model.IntVar] = []
        for cabin_id, event_times in sorted(time_by_cabin.items()):
            if region.cabin_id is not None and region.cabin_id != cabin_id:
                continue
            if region.visit_index + 1 >= len(event_times):
                continue
            selected = selection_by_key.get(
                (cabin_id, region.visit_index, region.route_option_id)
            )
            if selected is None:
                continue
            source_time = event_times[region.visit_index]
            target_time = event_times[region.visit_index + 1]
            factors = (
                selected,
                comparison(
                    source_time,
                    sense="ge",
                    bound=region.source_lower_tick,
                ),
                comparison(
                    source_time,
                    sense="lt",
                    bound=region.source_upper_tick,
                ),
                comparison(
                    target_time,
                    sense="ge",
                    bound=region.target_lower_tick,
                ),
                comparison(
                    target_time,
                    sense="lt",
                    bound=region.target_upper_tick,
                ),
            )
            present = model.new_bool_var(
                f"timed_flow_present[{support_index},{cabin_id}]"
            )
            model.add_bool_and(factors).only_enforce_if(present)
            model.add_bool_or([*(factor.Not() for factor in factors), present])
            presences.append(present)

        assumption = model.new_bool_var(f"timed_flow_assumption[{support_index}]")
        model.add(sum(presences) >= item.count).only_enforce_if(assumption)
        model.add_assumption(assumption)
        literal_by_index[assumption.Index()] = DddTimedFlowThresholdLiteral(
            region=region,
            minimum_flow=item.count,
        )
    return literal_by_index


def _fix_aggregate_route_support(
    *,
    model: cp_model.CpModel,
    selection_by_key: dict[tuple[int, int, str], cp_model.IntVar],
    fixed_support: DddCpSatFixedSupport,
) -> dict[int, DddAggregateRouteCountLiteral]:
    selections_by_aggregate_key: dict[tuple[int, str], list[cp_model.IntVar]] = {}
    for (_, visit_index, route_option_id), variable in selection_by_key.items():
        selections_by_aggregate_key.setdefault(
            (visit_index, route_option_id), []
        ).append(variable)

    required_by_key = fixed_support.count_by_key

    literal_by_index: dict[int, DddAggregateRouteCountLiteral] = {}
    # Include master keys that have no corresponding CP-SAT route variable.
    # This can legitimately happen because the anonymous master relaxes cabin
    # identities and terminal visit depths.  The conditional equality below
    # then becomes ``0 == positive_count`` and lets CP-SAT return the offending
    # aggregate literal in an infeasibility core instead of raising an adapter
    # error before the solve.
    aggregate_keys = set(selections_by_aggregate_key) | set(required_by_key)
    for literal_index, key in enumerate(sorted(aggregate_keys)):
        visit_index, route_option_id = key
        count = required_by_key.get(key, 0)
        variables = selections_by_aggregate_key.get(key, ())
        assumption = model.new_bool_var(f"support_assumption[{literal_index}]")
        model.add(sum(variables) == count).only_enforce_if(assumption)
        model.add_assumption(assumption)
        literal = DddAggregateRouteCountLiteral(
            visit_index=visit_index,
            route_option_id=route_option_id,
            count=count,
        )
        literal_by_index[assumption.Index()] = literal
    return literal_by_index


def _add_nearest_support_objective(
    *,
    model: cp_model.CpModel,
    selection_by_key: dict[tuple[int, int, str], cp_model.IntVar],
    nearest_support: DddCpSatFixedSupport,
) -> tuple[tuple[DddAggregateRouteCountLiteral, ...], cp_model.LinearExpr]:
    selections_by_aggregate_key: dict[tuple[int, str], list[cp_model.IntVar]] = {}
    for (_, visit_index, route_option_id), variable in selection_by_key.items():
        selections_by_aggregate_key.setdefault(
            (visit_index, route_option_id), []
        ).append(variable)

    center_by_key = nearest_support.count_by_key
    aggregate_keys = tuple(
        sorted(set(selections_by_aggregate_key) | set(center_by_key))
    )
    center = tuple(
        DddAggregateRouteCountLiteral(
            visit_index=visit_index,
            route_option_id=route_option_id,
            count=center_by_key.get((visit_index, route_option_id), 0),
        )
        for visit_index, route_option_id in aggregate_keys
    )
    distance_terms: list[cp_model.IntVar] = []
    for coordinate_index, literal in enumerate(center):
        variables = selections_by_aggregate_key.get(
            (literal.visit_index, literal.route_option_id), ()
        )
        maximum = max(len(variables), literal.count)
        distance = model.new_int_var(
            0,
            maximum,
            f"support_distance[{coordinate_index}]",
        )
        model.add_abs_equality(distance, sum(variables) - literal.count)
        distance_terms.append(distance)
    return center, cp_model.LinearExpr.sum(distance_terms)


def _exclude_solution_and_replace_hint(
    *,
    model: cp_model.CpModel,
    solver: cp_model.CpSolver,
    selection_by_key: dict[tuple[int, int, str], cp_model.IntVar],
    time_by_cabin: dict[int, list[cp_model.IntVar]],
    active_by_cabin: dict[int, list[cp_model.IntVar]],
    minimum_hamming_distance: int,
) -> None:
    selections = tuple(variable for _, variable in sorted(selection_by_key.items()))
    differing_literals = tuple(
        (1 - variable) if solver.value(variable) else variable
        for variable in selections
    )
    if minimum_hamming_distance > len(differing_literals):
        raise ValueError("DDD CP-SAT Hamming distance exceeds the route-variable count")
    model.add(sum(differing_literals) >= minimum_hamming_distance)
    model.clear_hints()
    for variable in selections:
        model.add_hint(variable, solver.value(variable))
    for cabin_id in sorted(time_by_cabin):
        for variable in time_by_cabin[cabin_id]:
            model.add_hint(variable, solver.value(variable))
        for variable in active_by_cabin[cabin_id]:
            model.add_hint(variable, solver.value(variable))


def _validate_excluded_schedules(
    problem: DddNetworkTimeProblem,
    excluded_schedules: tuple[tuple[DddRecoveredSchedule, ...], ...],
) -> None:
    expected_cabin_ids = tuple(
        sorted(start.cabin_id for start in problem.movement_problem.starts)
    )
    fingerprints: set[tuple[tuple[int, tuple[str, ...]], ...]] = set()
    for schedules in excluded_schedules:
        fingerprint = tuple(
            sorted(
                (schedule.cabin_id, schedule.route_option_ids) for schedule in schedules
            )
        )
        if tuple(cabin_id for cabin_id, _ in fingerprint) != expected_cabin_ids:
            raise ValueError(
                "DDD CP-SAT excluded schedule cabin IDs differ from the problem"
            )
        if fingerprint in fingerprints:
            raise ValueError("DDD CP-SAT excluded schedules must be unique")
        fingerprints.add(fingerprint)


def _exclude_route_patterns(
    *,
    model: cp_model.CpModel,
    selection_by_key: dict[tuple[int, int, str], cp_model.IntVar],
    excluded_schedules: tuple[tuple[DddRecoveredSchedule, ...], ...],
    minimum_hamming_distance: int,
) -> None:
    all_keys = tuple(sorted(selection_by_key))
    for schedules in excluded_schedules:
        selected_keys = {
            (schedule.cabin_id, visit_index, route_option_id)
            for schedule in schedules
            for visit_index, route_option_id in enumerate(schedule.route_option_ids)
        }
        unknown_keys = selected_keys - selection_by_key.keys()
        if unknown_keys:
            raise ValueError(
                "DDD CP-SAT excluded schedule references unknown route selections"
            )
        differing_literals = tuple(
            (1 - selection_by_key[key])
            if key in selected_keys
            else selection_by_key[key]
            for key in all_keys
        )
        if minimum_hamming_distance > len(differing_literals):
            raise ValueError(
                "DDD CP-SAT Hamming distance exceeds the route-variable count"
            )
        model.add(sum(differing_literals) >= minimum_hamming_distance)


def _deterministic_visit_structure(
    movement: DddMovementProblem,
    start_state_id: str,
    max_visit_count: int,
) -> tuple[tuple[str, ...], tuple[tuple[DddRouteOption, ...], ...]]:
    state_id = start_state_id
    states = [state_id]
    options_by_visit: list[tuple[DddRouteOption, ...]] = []
    for _ in range(max_visit_count):
        options = movement.route_options_by_state_id.get(state_id, ())
        if not options:
            raise ValueError(f"DDD CP-SAT state {state_id!r} has no route option")
        target_ids = {option.to_state_id for option in options}
        if len(target_ids) != 1:
            raise ValueError(
                "DDD CP-SAT v1 requires route options to reconverge at every visit"
            )
        options_by_visit.append(options)
        state_id = next(iter(target_ids))
        states.append(state_id)
    return tuple(states), tuple(options_by_visit)


def _add_resource_intervals(
    *,
    model: cp_model.CpModel,
    movement: DddMovementProblem,
    cabin_id: int,
    visit_index: int,
    event_time: cp_model.IntVar,
    selected: cp_model.IntVar,
    option: DddRouteOption,
    intervals_by_resource: dict[str, list[cp_model.IntervalVar]],
) -> None:
    for usage_index, usage in enumerate(option.resource_usages):
        if usage.resource_id not in intervals_by_resource:
            continue
        resource = movement.resources_by_id[usage.resource_id]
        size_tick = (
            usage.leader_clear_offset_tick
            - usage.follower_enter_offset_tick
            + usage.separation_after_tick(resource.minimum_headway_tick)
        )
        if size_tick <= 0:
            raise ValueError("DDD CP-SAT resource interval must have positive size")
        entry = event_time + usage.follower_enter_offset_tick
        if usage.follower_enter_offset_tick == 0:
            present = selected
        else:
            present = model.new_bool_var(
                f"resource_active[{cabin_id},{visit_index},{usage_index}]"
            )
            model.add_implication(present, selected)
            model.add(entry <= movement.operational_end_tick).only_enforce_if(present)
            model.add(entry >= movement.operational_end_tick + 1).only_enforce_if(
                [selected, present.Not()]
            )
        interval = model.new_optional_fixed_size_interval_var(
            entry,
            size_tick,
            present,
            f"resource[{usage.resource_id},{cabin_id},{visit_index},{usage_index}]",
        )
        intervals_by_resource[usage.resource_id].append(interval)


def _extract_schedules(
    *,
    problem: DddNetworkTimeProblem,
    solver: cp_model.CpSolver,
    states_by_cabin: dict[int, tuple[str, ...]],
    time_by_cabin: dict[int, list[cp_model.IntVar]],
    active_by_cabin: dict[int, list[cp_model.IntVar]],
    selection_by_key: dict[tuple[int, int, str], cp_model.IntVar],
) -> tuple[DddRecoveredSchedule, ...]:
    options_by_state = problem.movement_problem.route_options_by_state_id
    schedules: list[DddRecoveredSchedule] = []
    for start in sorted(
        problem.movement_problem.starts,
        key=lambda item: item.cabin_id,
    ):
        route_option_ids: list[str] = []
        event_count = 1
        for visit_index, state_id in enumerate(states_by_cabin[start.cabin_id][:-1]):
            if not solver.value(active_by_cabin[start.cabin_id][visit_index]):
                break
            options = options_by_state[state_id]
            selected = tuple(
                option.id
                for option in options
                if solver.value(
                    selection_by_key[(start.cabin_id, visit_index, option.id)]
                )
            )
            if len(selected) != 1:
                raise RuntimeError("DDD CP-SAT solution has no unique selected route")
            route_option_ids.append(selected[0])
            event_count += 1
        events = tuple(
            DddExactTimedEvent(
                event_index=index,
                state_id=states_by_cabin[start.cabin_id][index],
                time_seconds=ddd_tick_to_seconds(
                    solver.value(time_by_cabin[start.cabin_id][index])
                ),
            )
            for index in range(event_count)
        )
        route_ids = tuple(route_option_ids)
        objective_value = problem.objective.exact_value(
            route_ids,
            events[-1].state_id,
            events[-1].time_seconds,
            tolerance_seconds=0.0,
        )
        schedules.append(
            DddRecoveredSchedule(
                cabin_id=start.cabin_id,
                route_option_ids=route_ids,
                events=events,
                objective_value=objective_value,
            )
        )
    return tuple(schedules)
