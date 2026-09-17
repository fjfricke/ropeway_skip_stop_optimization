"""Waiting-only feasibility diagnostic for collision-bearing fixed line plans.

The native reservoir movement builder owns all physical constraints. Fleet,
complete route sequences, and every dispatch are fixed. No search controller or
implicit dispatch repair is introduced. Passenger allocation follows timing.
"""
from __future__ import annotations

from dataclasses import asdict
from time import perf_counter
from types import SimpleNamespace

from ortools.sat.python import cp_model

from ...models import DddRouteDecision
from ...reservoir_cp_sat import _movement_values
from ...reservoir_cp_sat_movement import build_reservoir_cp_movement
from ...reservoir_cp_sat_certificate import (
    DddReservoirCpPlan, DddReservoirCpTrip, validate_reservoir_cp_plan,
)
from ...time_ticks import ddd_seconds_to_tick as tick
from .passengers import optimize_waiting_timetable_passengers


def validate_fixed_candidate(problem, candidate, dispatch_end_tick):
    """Accept mutual collisions, never malformed individual trajectories."""
    if candidate.ride_counts:
        raise ValueError('repair input must contain movements only; passengers are reassigned')
    trips = candidate.trips
    if not trips or [t.cabin_id for t in trips] != list(range(len(trips))):
        raise ValueError('repair requires a nonempty canonical cabin prefix')
    dispatches = [t.switch_ticks[0] for t in trips]
    if dispatches != sorted(dispatches) or any(d > dispatch_end_tick for d in dispatches):
        raise ValueError('fixed dispatches violate the original line window/order')
    cycle = len(problem.cycle_states)
    service_end = problem.resolved_core.passenger_service_end_tick
    for trip in trips:
        validate_reservoir_cp_plan(problem, DddReservoirCpPlan((trip,), {}))
        n = len(trip.route_option_ids)
        if any(trip.wait_ticks) or n % cycle:
            raise ValueError('repair input must be a complete no-wait line trajectory')
        if trip.return_tick < service_end or (n > cycle and trip.switch_ticks[n-cycle] >= service_end):
            raise ValueError('input violates first complete return at/after service deadline')


def build_waiting_only_repair(problem, candidate, *, dispatch_end_tick, deadline=None):
    validate_fixed_candidate(problem, candidate, dispatch_end_tick)
    built = build_reservoir_cp_movement(problem, deadline=deadline)
    model = built.model
    by_cabin = {t.cabin_id: t for t in candidate.trips}
    cycle = len(problem.cycle_states)
    service_end = problem.resolved_core.passenger_service_end_tick
    for k, states in built.states_by_cabin.items():
        trip = by_cabin.get(k)
        n = len(trip.route_option_ids) if trip else 0
        for i in range(len(states)):
            model.add(built.active_by_cabin[k][i] == int(i < n))
            if i < len(states)-1:
                for option in problem.movement.route_options_by_state_id[states[i]]:
                    model.add(built.selection_by_key[k,i,option.id] == int(i < n and trip.route_option_ids[i] == option.id))
        if trip:
            # This equality is mandatory: waiting is the ONLY free timing decision.
            model.add(built.time_by_cabin[k][0] == trip.switch_ticks[0])
            model.add(built.time_by_cabin[k][n] >= service_end)
            if n > cycle:
                model.add(built.time_by_cabin[k][n-cycle] <= service_end-1)
    hints = _movement_values(problem, SimpleNamespace(movement=built), candidate)
    for index, value in hints.items():
        model.add_hint(model.get_int_var_from_proto_index(index), value)
    error = model.validate()
    if error:
        raise ValueError(error)
    return built


def extract_fixed_routes(candidate, built, value):
    return DddReservoirCpPlan(tuple(
        DddReservoirCpTrip(t.cabin_id, t.route_option_ids,
            tuple(int(value(built.time_by_cabin[t.cabin_id][i])) for i in range(len(t.route_option_ids))),
            tuple(int(value(built.wait_steps_by_key[t.cabin_id,i])) * built.waiting_step_tick for i in range(len(t.route_option_ids))),
            int(value(built.time_by_cabin[t.cabin_id][len(t.route_option_ids)])))
        for t in candidate.trips), {})


def solve_waiting_only_repair(problem, candidate, *, dispatch_end_tick,
        time_limit_seconds=120.0, passenger_seconds=10.0, workers=12, seed=0,
        event_callback=None, movement_callback=None, checkpoint_callback=None, log_path=None):
    if time_limit_seconds <= 0 or passenger_seconds <= 0 or not 1 <= workers <= 12:
        raise ValueError('invalid repair budget/workers')
    started = perf_counter(); deadline = started + time_limit_seconds
    emit = event_callback or (lambda event: None)
    result = {
        'schema': 'reservoir_waiting_only_repair_v1',
        'scope': 'FIXED_K_FIXED_FULL_ROUTES_FIXED_DISPATCH_FIRST_RETURN',
        'physical_fingerprint': problem.fingerprint,
        'dispatch_ticks': [t.switch_ticks[0] for t in candidate.trips],
        'fleet_size': len(candidate.trips), 'workers': workers, 'seed': seed,
        'waiting_policy': asdict(problem.waiting_policy),
        'passenger_optimality_scope': 'REPAIRED_TIMETABLE_ONLY',
        'global_bound': None, 'input_is_validated_incumbent': False,
        'capacity_optimal': False, 'plan': None,
    }
    emit({'phase':'building', 'elapsed_seconds':0})
    try:
        built = build_waiting_only_repair(problem, candidate, dispatch_end_tick=dispatch_end_tick, deadline=deadline)
    except TimeoutError:
        return {**result, 'status':'BUILD_TIMEOUT', 'total_wall_seconds':perf_counter()-started}
    result['build_seconds'] = perf_counter()-started
    result['variables'] = len(built.model.proto.variables)
    result['constraints'] = len(built.model.proto.constraints)
    remaining = deadline-perf_counter()
    if remaining <= 0:
        return {**result, 'status':'BUILD_TIMEOUT', 'total_wall_seconds':perf_counter()-started}
    solver = cp_model.CpSolver()
    # Feasibility first. OPTIMAL from a satisfaction model is NOT capacity optimality.
    solver.parameters.stop_after_first_solution = True
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = seed
    solver.parameters.max_time_in_seconds = max(0.001, remaining-min(passenger_seconds, remaining*0.2))
    solver.parameters.log_search_progress = log_path is not None
    solver.parameters.log_to_stdout = False
    solver.parameters.max_memory_in_mb = 32 * 1024
    emit({'phase':'timing', 'elapsed_seconds':perf_counter()-started,
          'variables':result['variables'], 'constraints':result['constraints']})
    before = perf_counter()
    if log_path is not None:
        with log_path.open('w') as stream:
            solver.log_callback = lambda line: (stream.write(line+'\n'), stream.flush())
            status = solver.solve(built.model)
    else:
        status = solver.solve(built.model)
    result.update(timing_status=solver.status_name(status), timing_seconds=perf_counter()-before,
                  response_stats=solver.response_stats(), branches=solver.num_branches,
                  solver_conflicts=solver.num_conflicts)
    if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        result.update(status='INFEASIBLE_FIXED_CANDIDATE' if status == cp_model.INFEASIBLE else 'UNKNOWN',
                      total_wall_seconds=perf_counter()-started)
        emit({'phase':'finished', 'status':result['status'], 'elapsed_seconds':result['total_wall_seconds']})
        return result
    movement = extract_fixed_routes(candidate, built, solver.value)
    validation_start = perf_counter()
    validate_reservoir_cp_plan(problem, movement)
    if any(a.switch_ticks[0] != b.switch_ticks[0] or a.route_option_ids != b.route_option_ids
           for a,b in zip(candidate.trips,movement.trips,strict=True)):
        raise RuntimeError('waiting-only repair altered fixed decisions')
    result['movement_validation_seconds'] = perf_counter()-validation_start
    result['first_valid_timing_seconds'] = perf_counter()-started
    result['total_wait_tick'] = sum(sum(t.wait_ticks) for t in movement.trips)
    result['maximum_wait_tick'] = max(w for t in movement.trips for w in t.wait_ticks)
    result['positive_wait_visits'] = sum(w > 0 for t in movement.trips for w in t.wait_ticks)
    if movement_callback:
        movement_callback(movement)
    emit({'phase':'passengers', 'elapsed_seconds':perf_counter()-started,
          'total_wait_tick':result['total_wait_tick']})
    remaining = deadline-perf_counter()
    if remaining <= 0:
        return {**result, 'status':'TIMING_FEASIBLE_PASSENGERS_PENDING',
                'plan':movement, 'total_wall_seconds':perf_counter()-started}
    passengers = optimize_waiting_timetable_passengers(problem, movement,
        time_limit_seconds=min(passenger_seconds, remaining))
    metrics = validate_reservoir_cp_plan(problem, passengers.plan)
    if checkpoint_callback:
        checkpoint_callback(passengers.plan)
    result.update(status='REPAIRED', plan=passengers.plan, metrics=asdict(metrics),
                  passengers={k:v for k,v in asdict(passengers).items() if k!='plan'},
                  total_wall_seconds=perf_counter()-started)
    emit({'phase':'finished','status':'REPAIRED','elapsed_seconds':result['total_wall_seconds'],
          'served':metrics.served, 'unserved':metrics.unserved})
    return result
