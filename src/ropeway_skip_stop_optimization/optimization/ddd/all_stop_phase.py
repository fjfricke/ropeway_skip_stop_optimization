"""Exact common-phase All-Stop reference with integer passengers."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
import math
from time import perf_counter

from ortools.sat.python import cp_model

from .models import DddRouteDecision
from .reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    DddReservoirCpTrip,
    validate_reservoir_cp_plan,
)
from .reservoir_cp_sat_problem import DddReservoirCpSatProblem
from .route_topology import unique_stop_route_option
from .time_ticks import ddd_seconds_to_tick


@dataclass(frozen=True, slots=True)
class AllStopPhaseConfig:
    cabins: int
    dispatch_window_end_seconds: float | None = None
    objective: str = "unserved"
    require_full_service: bool = False
    time_limit_seconds: float = 60.0
    workers: int = 12
    seed: int = 0
    log_search_progress: bool = False
    compact_time_links: bool = False
    phase_hint_tick: int | None = None

    def validate(self, problem: DddReservoirCpSatProblem) -> None:
        if type(self.cabins) is not int or not 1 <= self.cabins <= problem.available_fleet_count:
            raise ValueError("All-Stop phase cabins must lie within the available fleet")
        if self.objective not in ("unserved", "journey_time"):
            raise ValueError("All-Stop phase objective must be unserved or journey_time")
        if self.objective == "journey_time" and not self.require_full_service:
            raise ValueError("journey_time phase comparison requires full service")
        if self.dispatch_window_end_seconds is not None and (
            not math.isfinite(self.dispatch_window_end_seconds)
            or self.dispatch_window_end_seconds < 0
            or ddd_seconds_to_tick(self.dispatch_window_end_seconds)
            > ddd_seconds_to_tick(problem.dispatch_end_seconds)
        ):
            raise ValueError("All-Stop phase dispatch window is outside the problem domain")
        if not math.isfinite(self.time_limit_seconds) or self.time_limit_seconds <= 0:
            raise ValueError("All-Stop phase time limit must be positive")
        if type(self.workers) is not int or self.workers <= 0:
            raise ValueError("All-Stop phase workers must be positive")


@dataclass(frozen=True, slots=True)
class PreparedAllStopPhase:
    problem: DddReservoirCpSatProblem
    config: AllStopPhaseConfig
    cycle_tick: int
    offsets: tuple[int, ...]
    maximum_phase_tick: int
    trips: tuple[DddReservoirCpTrip, ...]


def prepare_all_stop_phase(
    problem: DddReservoirCpSatProblem,
    config: AllStopPhaseConfig,
) -> PreparedAllStopPhase:
    problem.validate()
    config.validate(problem)
    stops = tuple(
        unique_stop_route_option(problem.movement, state, error_context="All-Stop phase")
        for state in problem.cycle_states
    )
    cycle_tick = sum(option.duration_tick for option in stops)
    offsets = tuple((k * cycle_tick) // config.cabins for k in range(config.cabins))
    gaps = tuple(
        offsets[k + 1] - offsets[k] for k in range(config.cabins - 1)
    ) + (cycle_tick - offsets[-1],)
    binding = max(
        usage.leader_clear_offset_tick
        + usage.separation_after_tick(
            problem.resolved_core.resources_by_id[usage.resource_id].minimum_headway_tick
        )
        - usage.follower_enter_offset_tick
        for option in stops
        for usage in option.resource_usages
    )
    if problem.boundary_policy is not None:
        binding = max(binding, problem.boundary_policy.headway_tick)
    if min(gaps) < binding:
        raise ValueError("requested regular All-Stop fleet violates its binding headway")
    dispatch_end = ddd_seconds_to_tick(
        problem.dispatch_end_seconds
        if config.dispatch_window_end_seconds is None
        else config.dispatch_window_end_seconds
    )
    # Search the complete common-phase domain. A one-headway symmetry reduction
    # is not generally valid for a finite demand/recovery horizon, and the
    # balanced tick gaps are not even identical when C is indivisible by K.
    maximum_phase = dispatch_end - offsets[-1]
    if maximum_phase < 0:
        raise ValueError("All-Stop phase dispatch window cannot contain the regular fleet")

    service_end = problem.resolved_core.passenger_service_end_tick
    trips = []
    for cabin, dispatch_offset in enumerate(offsets):
        state, tick = problem.entry_state_id, dispatch_offset
        option_ids, switch_ticks = [], []
        while True:
            option = unique_stop_route_option(
                problem.movement, state, error_context="All-Stop phase"
            )
            option_ids.append(option.id)
            switch_ticks.append(tick)
            state, tick = option.to_state_id, tick + option.duration_tick
            if state == problem.entry_state_id and tick >= service_end:
                break
        if tick > problem.resolved_core.operational_end_tick:
            raise ValueError("All-Stop phase recovery horizon is too short")
        trips.append(
            DddReservoirCpTrip(
                cabin,
                tuple(option_ids),
                tuple(switch_ticks),
                (0,) * len(option_ids),
                tick,
            )
        )
    return PreparedAllStopPhase(
        problem, config, cycle_tick, offsets, maximum_phase, tuple(trips)
    )


def solve_all_stop_phase(
    prepared: PreparedAllStopPhase,
    *,
    event_callback=None,
    build_only: bool = False,
    deadline: float | None = None,
) -> tuple[dict, DddReservoirCpPlan | None]:
    started = perf_counter()
    problem, config = prepared.problem, prepared.config
    model = cp_model.CpModel()
    phase = model.new_int_var(0, prepared.maximum_phase_tick, "common_phase")
    if config.phase_hint_tick is not None:
        if not 0 <= config.phase_hint_tick <= prepared.maximum_phase_tick:
            raise ValueError("phase hint lies outside the reference domain")
        model.add_hint(phase, config.phase_hint_tick)
    groups = {group.id: group for group in problem.demand_groups}
    visits = {}
    options = {option.id: option for option in problem.resolved_core.route_options}
    for trip in prepared.trips:
        for index, (option_id, base_tick) in enumerate(
            zip(trip.route_option_ids, trip.switch_ticks, strict=True)
        ):
            visits[trip.cabin_id, index] = (options[option_id], base_tick)

    visits_per_cycle = len(problem.cycle_states)
    early_return = {}
    service_end = problem.resolved_core.passenger_service_end_tick
    for trip in prepared.trips:
        previous_return = trip.return_tick - prepared.cycle_tick
        early = model.new_bool_var(f"early_return[{trip.cabin_id}]")
        model.add(phase + previous_return >= service_end).only_enforce_if(early)
        model.add(phase + previous_return <= service_end - 1).only_enforce_if(
            early.negated()
        )
        early_return[trip.cabin_id] = early

    q_vars, q_data = {}, {}
    by_group = defaultdict(list)
    by_leg = defaultdict(list)
    horizon = problem.resolved_core.passenger_service_end_tick
    for ride in problem.passenger_build.ride_candidates:
        board = visits.get((ride.cabin_id, ride.board_visit_index))
        alight = visits.get((ride.cabin_id, ride.alight_visit_index))
        if board is None or alight is None:
            continue
        board_option, board_base = board
        alight_option, alight_base = alight
        group = groups[ride.demand_group_id]
        release = ddd_seconds_to_tick(group.release_time_seconds)
        departure_base = board_base + ddd_seconds_to_tick(
            board_option.platform_exit_offset_seconds
        )
        arrival_base = alight_base + ddd_seconds_to_tick(
            alight_option.platform_entry_offset_seconds
        )
        if (
            board_option.decision is not DddRouteDecision.STOP
            or alight_option.decision is not DddRouteDecision.STOP
            or arrival_base > horizon
            or departure_base + prepared.maximum_phase_tick < release
        ):
            continue
        q = model.new_int_var(0, min(group.count, problem.cabin_capacity), f"q[{ride.id}]")
        if not config.compact_time_links or departure_base < release or arrival_base + prepared.maximum_phase_tick > horizon:
            used = model.new_bool_var(f"used[{ride.id}]")
            model.add(q >= 1).only_enforce_if(used)
            model.add(q == 0).only_enforce_if(used.negated())
            model.add(phase + departure_base >= release).only_enforce_if(used)
            model.add(phase + arrival_base <= horizon).only_enforce_if(used)
        last_lap_start = len(prepared.trips[ride.cabin_id].route_option_ids) - visits_per_cycle
        if ride.alight_visit_index >= last_lap_start:
            model.add(q == 0).only_enforce_if(early_return[ride.cabin_id])
        q_vars[ride.id] = q
        q_data[ride.id] = (ride, arrival_base, release)
        by_group[ride.demand_group_id].append(q)
        for leg in range(ride.board_visit_index, ride.alight_visit_index):
            by_leg[ride.cabin_id, leg].append(q)

    for group_id, group in groups.items():
        if config.compact_time_links and config.require_full_service:
            model.add(sum(by_group[group_id]) == group.count)
        else:
            model.add(sum(by_group[group_id]) <= group.count)
    for values in by_leg.values():
        model.add(sum(values) <= problem.cabin_capacity)
    served = sum(q_vars.values())
    total_demand = sum(group.count for group in groups.values())
    if config.require_full_service:
        model.add(served == total_demand)

    if config.objective == "unserved":
        model.maximize(served)
    else:
        terms = []
        for ride_id, q in q_vars.items():
            _, arrival_base, release = q_data[ride_id]
            product = model.new_int_var(
                0,
                problem.cabin_capacity * prepared.maximum_phase_tick,
                f"phase_product[{ride_id}]",
            )
            model.add_multiplication_equality(product, (q, phase))
            terms.append((arrival_base - release) * q + product)
        model.minimize(sum(terms))

    if build_only:
        return (
            {
                "schema": "all_stop_common_phase_result_v1",
                "solver_status": "NOT_RUN",
                "proven_optimal": False,
                "objective": config.objective,
                "proof_scope": "REGULAR_NO_WAIT_ALL_STOP_COMMON_PHASE",
                "cycle_tick": prepared.cycle_tick,
                "cabins": config.cabins,
                "offsets": prepared.offsets,
                "maximum_phase_tick": prepared.maximum_phase_tick,
                "phase_tick": None,
                "metrics": None,
                "model_stats": {
                    "variables": len(model.proto.variables),
                    "constraints": len(model.proto.constraints),
                    "ride_variables": len(q_vars),
                },
                "native_objective": None,
                "native_bound": None,
                "response_stats": None,
                "total_seconds": perf_counter() - started,
            },
            None,
        )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = (
        config.time_limit_seconds if deadline is None
        else max(0.001, min(config.time_limit_seconds, deadline - perf_counter()))
    )
    solver.parameters.num_search_workers = config.workers
    solver.parameters.random_seed = config.seed
    solver.parameters.log_search_progress = config.log_search_progress
    status_code = solver.solve(model)
    status = solver.status_name(status_code)
    plan = None
    metrics = None
    if status_code in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        phase_tick = solver.value(phase)
        trips = tuple(
            DddReservoirCpTrip(
                trip.cabin_id,
                (
                    trip.route_option_ids[:-visits_per_cycle]
                    if solver.value(early_return[trip.cabin_id])
                    else trip.route_option_ids
                ),
                tuple(
                    tick + phase_tick
                    for tick in (
                        trip.switch_ticks[:-visits_per_cycle]
                        if solver.value(early_return[trip.cabin_id])
                        else trip.switch_ticks
                    )
                ),
                (
                    trip.wait_ticks[:-visits_per_cycle]
                    if solver.value(early_return[trip.cabin_id])
                    else trip.wait_ticks
                ),
                trip.return_tick
                + phase_tick
                - (
                    prepared.cycle_tick
                    if solver.value(early_return[trip.cabin_id])
                    else 0
                ),
            )
            for trip in prepared.trips
        )
        ride_counts = {
            ride_id: solver.value(var)
            for ride_id, var in q_vars.items()
            if solver.value(var) > 0
        }
        plan = DddReservoirCpPlan(trips, ride_counts)
        metrics = validate_reservoir_cp_plan(problem, plan)
        if event_callback is not None:
            event_callback(
                {
                    "kind": "validated_incumbent",
                    "elapsed_seconds": perf_counter() - started,
                    "phase_tick": phase_tick,
                    "served": metrics.served,
                    "unserved": metrics.unserved,
                    "journey_time_tick": metrics.journey_time_tick,
                }
            )
    result = {
        "schema": "all_stop_common_phase_result_v1",
        "solver_status": status,
        "proven_optimal": status_code == cp_model.OPTIMAL,
        "objective": config.objective,
        "proof_scope": "REGULAR_NO_WAIT_ALL_STOP_COMMON_PHASE",
        "cycle_tick": prepared.cycle_tick,
        "cabins": config.cabins,
        "offsets": prepared.offsets,
        "maximum_phase_tick": prepared.maximum_phase_tick,
        "phase_tick": None if plan is None else plan.trips[0].switch_ticks[0],
        "metrics": None if metrics is None else asdict(metrics),
        "model_stats": {
            "variables": len(model.proto.variables),
            "constraints": len(model.proto.constraints),
            "ride_variables": len(q_vars),
        },
        "native_objective": (
            None if status_code not in (cp_model.FEASIBLE, cp_model.OPTIMAL) else solver.objective_value
        ),
        "native_bound": (
            None if status_code not in (cp_model.FEASIBLE, cp_model.OPTIMAL) else solver.best_objective_bound
        ),
        "response_stats": solver.response_stats(),
        "total_seconds": perf_counter() - started,
    }
    return result, plan
