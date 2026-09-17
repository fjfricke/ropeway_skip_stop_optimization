"""Small exact insertion checks; one worker, no performance campaign."""

from dataclasses import replace

import pytest
from ortools.sat.python import cp_model
from test_optimization_ddd_reservoir_cp_sat import problem, trip

from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import _extract
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_greedy import *
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_greedy.gurobi import (
    free_windows,
)


def tiny(fleet=2):
    p = problem(
        available_fleet_count=fleet, dispatch_end_seconds=3, dispatch_step_seconds=1
    )
    p = replace(
        p, demand_groups=(replace(p.demand_groups[0], release_time_seconds=0, count=1),)
    )
    return pilot_problem(
        replace(
            p,
            movement_core=replace(
                p.movement_core,
                passenger_service_end_seconds=3,
                operational_end_seconds=8,
            ),
        ),
        dispatch_end_seconds=3,
    )


@pytest.mark.parametrize("backend", ["cp_sat", "gurobi"])
def test_free_insertion_positive_served_matches_small_optimum(backend):
    r = solve_insertion(
        tiny(), DddReservoirCpPlan((), {}), backend=backend, seconds=3, workers=1
    )
    assert r["status"] == "OPTIMAL"
    assert r["metrics"]["served"] == 1
    assert r["local_unserved_bound"] == 0
    validate_lifecycle(tiny(), r["plan"])


def test_window_endpoints_and_union():
    assert free_windows([(4, 6), (2, 4), (10, 12)]) == [(None, 2), (6, 10), (12, None)]
    assert free_windows([]) == [(None, None)]


def test_lifecycle_rejects_early_return():
    p = tiny()
    with pytest.raises(ValueError, match="first return"):
        validate_lifecycle(
            replace(
                p,
                movement_core=replace(p.movement_core, passenger_service_end_seconds=5),
            ),
            DddReservoirCpPlan((trip(),), {}),
        )


def test_id_invariance_and_new_dispatch_before_old():
    p = tiny(fleet=3)
    first = DddReservoirCpPlan((trip(k=2, dispatch=3),), {})
    second = DddReservoirCpPlan((trip(k=0, dispatch=3),), {})
    a = prepare_insertion(p, first)
    b = prepare_insertion(p, second)
    assert a.fingerprint == b.fingerprint
    built = build_insertion(a)
    m = built.movement
    m.model.add(m.time_by_cabin[1][0] == 0)
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = 1
    s.parameters.max_time_in_seconds = 2
    status = s.solve(m.model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    plan = _extract(p, built, s.value)
    validate_lifecycle(p, plan)
    assert (
        next(t for t in plan.trips if t.cabin_id == 0).switch_ticks
        == first.trips[0].switch_ticks
    )


@pytest.mark.parametrize("backend", ["cp_sat", "gurobi"])
def test_construct_empty_and_retains_validated_plan(backend):
    p = tiny()
    r = construct_greedy(
        p,
        GreedyConfig(
            backend=backend,
            time_limit=4,
            insertion_time_limit=2,
            extended_time_limit=2,
            workers=1,
        ),
    )
    assert r["metrics"]["served"] == 1
    assert r["termination"] == "FULL_SERVICE"
    assert r["global_bound"] is None


def test_fleet_exhaustion_and_unknown_are_not_global_proofs():
    p = tiny(fleet=1)
    with pytest.raises(ValueError, match="fleet exhausted"):
        prepare_insertion(p, DddReservoirCpPlan((trip(),), {}))
    r = solve_insertion(p, DddReservoirCpPlan((), {}), seconds=0.0001, workers=1)
    assert r["status"] == "BUILD_TIMEOUT"
    assert r["plan"] is None and r["global_bound"] is None


@pytest.mark.parametrize("backend", ["cp_sat", "gurobi"])
@pytest.mark.parametrize("waiting,feasible", [(False, False), (True, True)])
def test_insertion_that_requires_origin_waiting(backend, waiting, feasible):
    p = tiny()
    p = replace(
        p,
        movement_core=replace(
            p.movement_core,
            resources=tuple(
                replace(r, headway_seconds=2, maximum_headway_seconds=2)
                if r.id == "rope_B"
                else r
                for r in p.movement_core.resources
            ),
        ),
    )
    outside = DddReservoirCpPlan((trip(dispatch=1),), {})
    built = build_insertion(prepare_insertion(p, outside))
    b = built.movement
    b.model.add(b.time_by_cabin[1][0] == 0)
    b.model.add(b.active_by_cabin[1][2] == 0)
    b.model.add(b.selection_by_key[1, 0, "A_stop"] == 1)
    b.model.add(b.selection_by_key[1, 1, "B_stop"] == 1)
    if not waiting:
        b.model.add(b.wait_steps_by_key[1, 0] == 0)
    if backend == "cp_sat":
        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = 1
        solver.parameters.max_time_in_seconds = 2
        status = solver.solve(b.model)
        assert (status in (cp_model.OPTIMAL, cp_model.FEASIBLE)) == feasible
        if feasible:
            validate_lifecycle(p, _extract(p, built, solver.value))
    else:
        from gurobipy import GRB

        from ropeway_skip_stop_optimization.optimization.ddd.reservoir_greedy.gurobi import (
            GurobiInsertion,
        )

        g = GurobiInsertion(built)
        try:
            g.model.Params.Threads = 1
            g.model.Params.TimeLimit = 2
            g.model.optimize()
            assert (g.model.SolCount > 0) == feasible
            if feasible:
                validate_lifecycle(p, _extract(p, built, g.value))
            else:
                assert g.model.Status == GRB.INFEASIBLE
        finally:
            g.model.dispose()


@pytest.mark.parametrize("backend", ["cp_sat", "gurobi"])
@pytest.mark.parametrize("objective", ["unserved", "journey_time"])
def test_two_cabin_optimum_matches_independent_waiting_enumeration(backend, objective):
    from itertools import product

    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
        DddReservoirCpTrip,
    )

    p = tiny()
    p = replace(
        p,
        demand_groups=(replace(p.demand_groups[0], count=2),),
        waiting_policy=replace(
            p.waiting_policy,
            step_seconds=1,
            maximum_wait_seconds_by_station_id=(("A", 1), ("B", 1)),
        ),
    )
    outside = DddReservoirCpPlan((trip(dispatch=1),), {})
    # Enumerate decisions independently; this fixture can have at most two laps.
    optimum = 0
    best_cost = 6_000_000
    for dispatch in range(4):
        for n in (2, 4):
            for decisions in product(("stop", "skip"), repeat=n):
                routes = tuple(
                    f"{'A' if i % 2 == 0 else 'B'}_{d}" for i, d in enumerate(decisions)
                )
                for waits in product(
                    *[(0, 1) if d == "stop" else (0,) for d in decisions]
                ):
                    times = []
                    now = dispatch * 1_000_000
                    for d, w in zip(decisions, waits):
                        times.append(now)
                        now += ((2 if d == "stop" else 1) + w) * 1_000_000
                    tr = DddReservoirCpTrip(
                        1,
                        routes,
                        tuple(times),
                        tuple(w * 1_000_000 for w in waits),
                        now,
                    )
                    plan = DddReservoirCpPlan((*outside.trips, tr), {})
                    try:
                        validate_lifecycle(p, plan)
                    except ValueError:
                        continue
                    # Independent direct assignment enumeration for the two persons.
                    rides = []
                    options = {o.id: o for o in p.resolved_core.route_options}
                    for q in p.passenger_build.ride_candidates:
                        t = plan.trips[q.cabin_id]
                        if q.alight_visit_index >= len(t.route_option_ids):
                            continue
                        bo = options[t.route_option_ids[q.board_visit_index]]
                        ao = options[t.route_option_ids[q.alight_visit_index]]
                        if (
                            bo.id.endswith("stop")
                            and ao.id.endswith("stop")
                            and t.switch_ticks[q.alight_visit_index] <= 3_000_000
                        ):
                            rides.append(q.id)
                    for subset in product((0, 1), repeat=len(rides)):
                        assignment = {
                            rid: count for rid, count in zip(rides, subset) if count
                        }
                        try:
                            metrics = validate_lifecycle(
                                p, DddReservoirCpPlan(plan.trips, assignment)
                            )
                        except ValueError:
                            continue
                        optimum = max(optimum, metrics.served)
                        best_cost = min(best_cost, metrics.journey_time_tick)
    r = solve_insertion(
        p, outside, backend=backend, objective=objective, seconds=3, workers=1
    )
    assert r["status"] == "OPTIMAL"
    assert optimum == 2
    if objective == "unserved":
        assert r["metrics"]["served"] == optimum
    if objective == "journey_time":
        assert r["metrics"]["journey_time_tick"] == best_cost
        assert r["local_journey_time_bound_tick"] == best_cost
        assert r["local_unserved_bound"] is None


@pytest.mark.parametrize("backend", ["cp_sat", "gurobi"])
def test_input_ids_do_not_change_optimal_value(backend):
    p = tiny(fleet=3)
    values = []
    for cid in (0, 2):
        r = solve_insertion(
            p,
            DddReservoirCpPlan((trip(k=cid, dispatch=3),), {}),
            backend=backend,
            seconds=3,
            workers=1,
        )
        assert r["status"] == "OPTIMAL"
        values.append(r["metrics"]["served"])
    assert values[0] == values[1]


@pytest.mark.parametrize("backend", ["cp_sat", "gurobi"])
def test_retry_relabels_candidate_and_has_unique_hints(backend):
    p = tiny(fleet=3)
    outside = DddReservoirCpPlan((trip(dispatch=3),), {})
    first = solve_insertion(p, outside, backend=backend, seconds=3, workers=1)
    second = solve_insertion(
        p, outside, backend=backend, seconds=3, workers=1, candidate_seed=first["plan"]
    )
    assert second["status"] == "OPTIMAL"
    assert second["metrics"]["served"] == first["metrics"]["served"]


@pytest.mark.parametrize("backend", ["cp_sat", "gurobi"])
@pytest.mark.parametrize("extra,feasible", [(0, True), (1, False)])
def test_shared_port_dispatch_against_return_neighbor_ticks(backend, extra, feasible):
    from test_reservoir_boundary import shared

    p = shared(tiny(), 1 + extra / 1_000_000)
    b = build_insertion(
        prepare_insertion(p, DddReservoirCpPlan((trip(dispatch=3),), {}))
    )
    m = b.movement
    m.model.add(m.time_by_cabin[1][0] == 0)
    m.model.add(m.active_by_cabin[1][2] == 0)
    for i, oid in enumerate(("A_stop", "B_stop")):
        m.model.add(m.selection_by_key[1, i, oid] == 1)
        m.model.add(m.wait_steps_by_key[1, i] == 0)
    if backend == "cp_sat":
        s = cp_model.CpSolver()
        s.parameters.num_search_workers = 1
        s.parameters.max_time_in_seconds = 2
        status = s.solve(m.model)
        assert (status == cp_model.OPTIMAL) == feasible
        if feasible:
            validate_lifecycle(p, _extract(p, b, s.value))
    else:
        from ropeway_skip_stop_optimization.optimization.ddd.reservoir_greedy.gurobi import (
            GurobiInsertion,
        )

        g = GurobiInsertion(b)
        try:
            g.model.Params.Threads = 1
            g.model.Params.TimeLimit = 2
            g.model.optimize()
            assert bool(g.model.SolCount) == feasible
            if feasible:
                validate_lifecycle(p, _extract(p, b, g.value))
        finally:
            g.model.dispose()


@pytest.mark.parametrize("backend", ["cp_sat", "gurobi"])
def test_journey_accepts_faster_service_without_serving_more(backend):
    p = tiny()
    q = next(
        r
        for r in p.passenger_build.ride_candidates
        if r.cabin_id == 0 and r.board_visit_index == 0 and r.alight_visit_index == 1
    )
    outside = DddReservoirCpPlan((trip(dispatch=1),), {q.id: 1})
    before = validate_lifecycle(p, outside)
    events = []
    r = construct_greedy(
        p,
        GreedyConfig(
            backend=backend, objective="journey_time", time_limit=5, workers=1
        ),
        initial_plan=outside,
        on_event=events.append,
    )
    assert r["metrics"]["served"] == before.served == 1
    assert r["metrics"]["journey_time_tick"] < before.journey_time_tick
    accepted = [e for e in events if e["kind"] == "accepted_insertion"]
    assert (
        accepted
        and accepted[0]["journey_time_tick"] == r["metrics"]["journey_time_tick"]
    )
    assert r["metrics"]["used_fleet"] == 2
    assert r["steps"][0]["local_unserved_bound"] is None


def test_all_stop_reference_does_not_disable_skip_stop_in_pilot():
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_arc_flow_problem import (
        DddReservoirOperatingMode,
    )

    source = replace(tiny(), operating_mode=DddReservoirOperatingMode.ALL_STOP)
    assert all(o.decision.value == "stop" for o in source.resolved_core.route_options)
    p = pilot_problem(source, waiting_seconds=1, dispatch_end_seconds=3)
    assert p.operating_mode == DddReservoirOperatingMode.SKIP_STOP
    built = build_insertion(prepare_insertion(p, DddReservoirCpPlan((), {})))
    assert any(oid.endswith("skip") for _, _, oid in built.movement.selection_by_key)
    assert source.fingerprint != p.fingerprint


def test_fixed_outside_arrivals_use_linear_costs_without_freezing_passengers():
    p = tiny(fleet=3)
    outside = DddReservoirCpPlan((trip(k=0, dispatch=0),), {})
    built = build_insertion(prepare_insertion(p, outside), objective="journey_time")
    passengers = built.passengers
    old_events = [e for e in passengers.alight_count if e[0] == 0]
    assert old_events
    for event in old_events:
        domain = list(passengers.alight_time[event].proto.domain)
        assert domain[0] == domain[-1]
        assert not any(key[:2] == event for key in passengers.unary)
    old_rides = [q for q in p.passenger_build.ride_candidates
                 if q.cabin_id == 0 and q.id in passengers.ride_count]
    assert old_rides
    assert any(list(passengers.ride_count[q.id].proto.domain)[-1] > 0
               for q in old_rides)
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.max_time_in_seconds = 2
    assert solver.solve(built.movement.model) == cp_model.OPTIMAL
    plan = _extract(p, built, solver.value)
    metrics = validate_lifecycle(p, plan)
    assert round(solver.objective_value) == metrics.journey_time_tick
