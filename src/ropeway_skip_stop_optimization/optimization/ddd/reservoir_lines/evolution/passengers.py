from __future__ import annotations

from collections import defaultdict
import math
from time import perf_counter

import gurobipy as gp
from gurobipy import GRB

from ...models import DddRouteDecision
from ...reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    validate_reservoir_cp_plan,
)
from ...time_ticks import ddd_seconds_to_tick
from .model import PassengerEvaluation, PassengerPotential


def optimize_fixed_movement_passengers(problem, movement: DddReservoirCpPlan, *, time_limit_seconds: float = 2.0, objective: str = "unserved") -> PassengerEvaluation:
    return _optimize_assignment(problem, movement, time_limit_seconds=time_limit_seconds, relaxed=False, objective=objective)


def evaluate_passenger_potential(problem, timetable: DddReservoirCpPlan, *, time_limit_seconds: float = 2.0) -> PassengerPotential:
    """Ignore only inter-cabin collisions. This never exports a certificate."""
    return _optimize_assignment(problem, timetable, time_limit_seconds=time_limit_seconds, relaxed=True)


def optimize_waiting_timetable_passengers(problem, movement: DddReservoirCpPlan, *, time_limit_seconds: float = 2.0) -> PassengerEvaluation:
    """Reassign integer passengers after a validated waiting-only repair."""
    return _optimize_assignment(problem, movement, time_limit_seconds=time_limit_seconds,
                                relaxed=False, allow_waiting=True)


def _optimize_assignment(problem, movement, *, time_limit_seconds, relaxed, allow_waiting=False, objective="unserved"):
    started = perf_counter()
    if movement.ride_counts:
        movement = DddReservoirCpPlan(movement.trips, {})
    if not allow_waiting and any(w for trip in movement.trips for w in trip.wait_ticks):
        raise ValueError("no-wait passenger evaluator received positive waiting")
    if not relaxed:
        validate_reservoir_cp_plan(problem, movement)
    trips = {trip.cabin_id: trip for trip in movement.trips}
    options = {item.id: item for item in problem.resolved_core.route_options}
    groups = {item.id: item for item in problem.demand_groups}
    service_end = problem.resolved_core.passenger_service_end_tick
    model = gp.Model("fixed_no_wait_line_passengers")
    model.Params.OutputFlag = 0
    model.Params.Threads = 1
    model.Params.MIPGap = 0
    if objective not in ("unserved", "journey_time", "service_then_journey"):
        raise ValueError("unknown passenger objective")
    variables = {}
    journey_coefficients = {}
    by_group = defaultdict(list)
    onboard = defaultdict(list)
    for candidate in problem.passenger_build.ride_candidates:
        trip = trips.get(candidate.cabin_id)
        if trip is None or candidate.alight_visit_index >= len(trip.route_option_ids):
            continue
        board_option = options[trip.route_option_ids[candidate.board_visit_index]]
        alight_option = options[trip.route_option_ids[candidate.alight_visit_index]]
        if (
            board_option.decision is not DddRouteDecision.STOP
            or alight_option.decision is not DddRouteDecision.STOP
            or board_option.platform_exit_offset_seconds is None
            or alight_option.platform_entry_offset_seconds is None
        ):
            continue
        group = groups[candidate.demand_group_id]
        board_tick = (
            trip.switch_ticks[candidate.board_visit_index]
            + ddd_seconds_to_tick(board_option.platform_exit_offset_seconds)
            + trip.wait_ticks[candidate.board_visit_index]
        )
        alight_tick = (
            trip.switch_ticks[candidate.alight_visit_index]
            + ddd_seconds_to_tick(alight_option.platform_entry_offset_seconds)
        )
        if (
            board_option.station_id != group.origin_station_id
            or alight_option.station_id != group.destination_station_id
            or board_tick < ddd_seconds_to_tick(group.release_time_seconds)
            or board_tick > service_end
            or alight_tick > service_end
        ):
            continue
        q = model.addVar(
            lb=0,
            ub=min(problem.cabin_capacity, group.count),
            vtype=GRB.INTEGER,
            name=candidate.id,
        )
        variables[candidate.id] = q
        journey_coefficients[candidate.id] = (
            alight_tick - service_end
        )
        by_group[group.id].append(q)
        for segment in range(candidate.board_visit_index, candidate.alight_visit_index):
            onboard[candidate.cabin_id, segment].append(q)
    for group_id, values in by_group.items():
        model.addConstr(gp.quicksum(values) <= groups[group_id].count)
    for values in onboard.values():
        model.addConstr(gp.quicksum(values) <= problem.cabin_capacity)
    served_expression = gp.quicksum(variables.values())
    journey_expression = gp.quicksum(
        journey_coefficients[key] * q for key, q in variables.items()
    )
    if objective == "journey_time":
        model.setObjective(
            journey_expression,
            GRB.MINIMIZE,
        )
    elif objective == "service_then_journey":
        # Gurobi solves higher-priority objectives to proven optimality before
        # proceeding to lower priorities.  Negative served therefore gives an
        # exact lexicographic max-served/min-journey assignment without a large
        # and numerically fragile scalar weight.
        model.ModelSense = GRB.MINIMIZE
        model.setObjectiveN(-served_expression, 0, priority=2, name="max_served")
        model.setObjectiveN(journey_expression, 1, priority=1, name="min_journey")
    else:
        model.setObjective(served_expression, GRB.MAXIMIZE)
    build_seconds = perf_counter() - started
    remaining = max(0.001, time_limit_seconds - build_seconds)
    model.Params.TimeLimit = remaining
    before = perf_counter()
    model.optimize()
    solve_seconds = perf_counter() - before
    status = model.Status
    status_name = {
        GRB.OPTIMAL: "OPTIMAL",
        GRB.TIME_LIMIT: "TIME_LIMIT",
        GRB.INTERRUPTED: "INTERRUPTED",
        GRB.INFEASIBLE: "INFEASIBLE",
    }.get(status, str(status))
    counts = {}
    if model.SolCount:
        counts = {key: int(round(var.X)) for key, var in variables.items() if var.X >= 0.5}
    plan = DddReservoirCpPlan(movement.trips, counts)
    before = perf_counter()
    if relaxed:
        # Validate every cabin and its assignment with the independent checker.
        # Only conflicts BETWEEN cabins are removed. Aggregate demand remains shared.
        candidates = {q.id: q for q in problem.passenger_build.ride_candidates}
        by_cabin = defaultdict(dict)
        assigned_by_group = defaultdict(int)
        for rid, count in counts.items():
            q = candidates[rid]
            by_cabin[q.cabin_id][rid] = count
            assigned_by_group[q.demand_group_id] += count
        try:
            for trip in plan.trips:
                validate_reservoir_cp_plan(
                    problem, DddReservoirCpPlan((trip,), by_cabin[trip.cabin_id])
                )
            if any(n > groups[g].count for g, n in assigned_by_group.items()):
                raise ValueError("relaxed assignment exceeded shared demand")
        except ValueError:
            model.dispose()
            raise
        served = sum(counts.values())
        unserved = sum(g.count for g in groups.values()) - served
    else:
        metrics = validate_reservoir_cp_plan(problem, plan)
        served, unserved = metrics.served, metrics.unserved
    validation_seconds = perf_counter() - before
    upper = None
    if objective == "unserved" and math.isfinite(model.ObjBound):
        upper = min(sum(group.count for group in problem.demand_groups), math.ceil(model.ObjBound - 1e-8))
    if relaxed:
        result = PassengerPotential(
            served, unserved, status == GRB.OPTIMAL, upper,
            build_seconds, solve_seconds, validation_seconds, status_name,
        )
        model.dispose()
        return result
    result = PassengerEvaluation(
        plan,
        served,
        unserved,
        status == GRB.OPTIMAL,
        upper,
        tuple(sorted(counts.items())),
        build_seconds,
        solve_seconds,
        validation_seconds,
        status_name,
        validate_reservoir_cp_plan(problem, plan).journey_time_tick,
    )
    model.dispose()
    return result
