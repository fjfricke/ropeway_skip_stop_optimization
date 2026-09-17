"""Fixed masks with free ordered dispatch, exact Waiting and variable lap count.

Uses the original reservoir physics, not No-Wait template-pair domains. A cabin
continues at each full-lap boundary strictly before the service deadline and
returns at the first such boundary on or after it. Downstream order is free.
"""
from dataclasses import asdict, replace
import math
from time import perf_counter
from types import SimpleNamespace

from ortools.sat.python import cp_model

from ...reservoir_cp_sat import _extract, build_reservoir_cp_sat, DddReservoirCpObjective
from ...reservoir_cp_sat_movement import build_reservoir_cp_movement
from ...reservoir_cp_sat_certificate import validate_reservoir_cp_plan
from ...trajectory_problem import DddTrajectoryWaitingPolicy
from ...trajectory_column_generation import DddTrajectoryWaitingDomain
from ...time_ticks import ddd_seconds_to_tick as tick
from ...cp_sat_certificate import stable_fingerprint
from ..catalog import line_patterns, option_for_pattern
from ..config import ReservoirLineCatalogProfile
from .decoder import minimum_dispatch_gap_tick
from .passengers import optimize_waiting_timetable_passengers
from .model import PassengerEvaluation


def with_pattern_waiting(problem, seconds, *, earliest_seconds=None):
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("pattern Waiting cap must be positive and finite")
    stations = sorted({o.station_id for o in problem.resolved_core.route_options})
    policy = DddTrajectoryWaitingPolicy(
        domain=DddTrajectoryWaitingDomain.BOUNDED_WAIT,
        step_seconds=0.000001,
        maximum_wait_seconds_by_station_id=tuple((s, seconds) for s in stations),
        earliest_wait_time_seconds=(problem.waiting_policy.earliest_wait_time_seconds
                                   if earliest_seconds is None else earliest_seconds))
    result = replace(problem, waiting_policy=policy)
    result.validate()
    return result


def constrain_pattern_lifecycle(problem, movement, pattern_ids, *, dispatch_end_tick):
    """Add only pattern/line-contract constraints to the complete physical model."""
    catalog = {p.id: p for p in line_patterns(problem, ReservoirLineCatalogProfile.RELEVANT)}
    if not pattern_ids or len(pattern_ids) > problem.available_fleet_count:
        raise ValueError("expected a nonempty fleet within the original fleet limit")
    if set(pattern_ids) - catalog.keys():
        raise ValueError("unknown pattern in Waiting subproblem")
    model = movement.model
    deadline = problem.resolved_core.passenger_service_end_tick
    cycle = len(problem.cycle_states)
    for k, states in movement.states_by_cabin.items():
        active, times = movement.active_by_cabin[k], movement.time_by_cabin[k]
        model.add(active[0] == int(k < len(pattern_ids)))
        if k >= len(pattern_ids):
            continue
        model.add(times[0] <= dispatch_end_tick)
        if k:
            model.add(times[0] >= movement.time_by_cabin[k-1][0] + minimum_dispatch_gap_tick(problem))
        for i, state in enumerate(states):
            if i and i % cycle == 0:
                # At a reached port: continue iff strictly before service end.
                returned = model.new_bool_var(f"line_return[{k},{i}]")
                model.add(returned == active[i-1] - active[i])
                model.add(times[i] >= deadline).only_enforce_if(returned)
                model.add(times[i] <= deadline-1).only_enforce_if(active[i])
            if i == len(states)-1:
                continue
            selected = option_for_pattern(problem, state, catalog[pattern_ids[k]])
            for option in problem.resolved_core.route_options_by_state_id[state]:
                literal = movement.selection_by_key[k, i, option.id]
                model.add(literal == (active[i] if option.id == selected.id else 0))


def build_pattern_waiting(problem, pattern_ids, *, dispatch_end_tick, joint=False, deadline=None):
    # Other optional cabins cannot affect this fixed-K model. Original IDs and
    # validation domain remain intact. No No-Wait template filtering is applied.
    if not 0 < len(pattern_ids) <= problem.available_fleet_count:
        raise ValueError("invalid fixed fleet")
    local = replace(problem, available_fleet_count=len(pattern_ids))
    if joint:
        built = build_reservoir_cp_sat(local, objective=DddReservoirCpObjective.UNSERVED,
                                      deadline=deadline)
        built.movement.model.minimize(sum(built.passengers.unserved.values()))
    else:
        built = SimpleNamespace(movement=build_reservoir_cp_movement(local, deadline=deadline),
                                passengers=SimpleNamespace(ride_count={}))
    constrain_pattern_lifecycle(local, built.movement, pattern_ids, dispatch_end_tick=dispatch_end_tick)
    error = built.movement.model.validate()
    if error:
        raise ValueError(error)
    return built


def solve_pattern_waiting(problem, pattern_ids, *, dispatch_end_tick, joint=False,
                          seconds=60, workers=12, seed=0, deadline=None):
    started = perf_counter()
    limit = min(started+seconds, deadline) if deadline is not None else started+seconds
    result = dict(solver_status="UNKNOWN", plan=None, passengers=None,
                  preparation_seconds=0.0, model_build_seconds=0.0, solve_seconds=0.0,
                  validation_seconds=0.0, model_stats={},
                  objective_scope="FIXED_ORDERED_PATTERNS_ALL_ALLOWED_WAITING_DISPATCHES" if joint
                  else "PASSENGERS_ON_FIRST_FEASIBLE_WAITING_TIMETABLE",
                  physical_fingerprint=problem.fingerprint,
                  waiting_policy=asdict(problem.waiting_policy), global_bound=None)
    try:
        built = build_pattern_waiting(problem, pattern_ids, dispatch_end_tick=dispatch_end_tick,
                                      joint=joint, deadline=limit)
    except TimeoutError:
        result.update(solver_status="BUILD_TIMEOUT", model_build_seconds=perf_counter()-started)
        return result
    model = built.movement.model
    result['model_build_seconds'] = perf_counter()-started
    result['model_stats'] = dict(variables=len(model.proto.variables), constraints=len(model.proto.constraints))
    result['model_fingerprint'] = stable_fingerprint(dict(
        version="ordered_pattern_waiting_variable_laps_v1", physical=problem.fingerprint,
        patterns=pattern_ids, dispatch_end_tick=dispatch_end_tick, joint=joint,
        ortools=__import__('ortools').__version__))
    remaining = limit-perf_counter()
    if remaining <= 0:
        result['solver_status'] = 'BUILD_TIMEOUT'
        return result
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = seed
    solver.parameters.stop_after_first_solution = not joint
    solver.parameters.max_time_in_seconds = max(.001, remaining - min(3.0 if not joint else 1.0, remaining*.15))
    before = perf_counter()
    status = solver.solve(model)
    result.update(solver_status=solver.status_name(status), solve_seconds=perf_counter()-before,
                  branches=solver.num_branches, solver_conflicts=solver.num_conflicts,
                  response_stats=solver.response_stats())
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return result
    before = perf_counter()
    plan = _extract(problem, built, solver.value)
    metrics = validate_reservoir_cp_plan(problem, plan)
    # The independent physical checker has a broader reservoir lifecycle.
    # Explicitly check the additional first-return line contract as well.
    end = problem.resolved_core.passenger_service_end_tick
    cycle = len(problem.cycle_states)
    for trip in plan.trips:
        n = len(trip.route_option_ids)
        if n % cycle or trip.return_tick < end or (n > cycle and trip.switch_ticks[n-cycle] >= end):
            raise RuntimeError("invalid first-return line lifecycle")
    result['validation_seconds'] = perf_counter()-before
    if joint:
        total = sum(g.count for g in problem.demand_groups)
        passengers = PassengerEvaluation(plan, metrics.served, metrics.unserved,
            status == cp_model.OPTIMAL, total-math.ceil(solver.best_objective_bound),
            tuple(sorted(plan.ride_counts.items())), result['model_build_seconds'],
            result['solve_seconds'], result['validation_seconds'], solver.status_name(status))
    elif limit > perf_counter():
        passengers = optimize_waiting_timetable_passengers(problem, plan,
                                        time_limit_seconds=max(.001, limit-perf_counter()))
    else:
        passengers = PassengerEvaluation(plan, 0, metrics.unserved, False, None, (), 0, 0, 0, 'NOT_RUN')
    result.update(plan=passengers.plan, passengers=passengers,
                  maximum_wait_tick=max(w for t in plan.trips for w in t.wait_ticks),
                  total_wait_tick=sum(sum(t.wait_ticks) for t in plan.trips),
                  rounds=[len(t.route_option_ids)//cycle for t in plan.trips],
                  total_wall_seconds=perf_counter()-started)
    return result
