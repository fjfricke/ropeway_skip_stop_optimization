"""Independent certificates and CP reference optima for the native encodings."""

from dataclasses import replace
from itertools import product

import pytest

pytest.importorskip("z3")
from test_optimization_ddd_reservoir_cp_sat import T, problem, trip

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_didp import prepare_small
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_capacity import (
    DddCpSatCapacityOptimizer,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
    DddIntegratedCpSatConfig,
    DddIntegratedCpSatOptimizer,
)
from ropeway_skip_stop_optimization.optimization.ddd.native_solvers import (
    NativeSolverConfig,
    build_native_model,
    prepare_native_structure,
    solve_native,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    validate_reservoir_cp_plan,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup


def tiny():
    p = problem(
        dispatch_end_seconds=3,
        dispatch_step_seconds=1,
        demand_groups=(EanDemandGroup("g", "A", "B", 0, 1),),
    )
    return replace(
        p,
        movement_core=replace(
            p.movement_core, passenger_service_end_seconds=3, operational_end_seconds=4
        ),
    )


@pytest.mark.parametrize("objective", ["journey_time", "unserved"])
def test_exhaustive_reservoir_routes_dispatch_and_assignment(objective):
    p = tiny()
    feasible = []
    # Independent enumeration through the original physical/passenger checker.
    for d in range(4):
        for n in (2, 4):
            for decisions in product(("stop", "skip"), repeat=n):
                routes = tuple(
                    f"{'A' if i % 2 == 0 else 'B'}_{s}" for i, s in enumerate(decisions)
                )
                t = trip(dispatch=d, routes=routes)
                candidates = [None, *p.passenger_build.ride_candidates]
                for q in candidates:
                    try:
                        m = validate_reservoir_cp_plan(
                            p, DddReservoirCpPlan((t,), {} if q is None else {q.id: 1})
                        )
                        feasible.append(
                            m.unserved
                            if objective == "unserved"
                            else m.journey_time_tick
                        )
                    except ValueError:
                        pass
    result, _plan = solve_native(
        p, NativeSolverConfig(objective=objective, time_limit=5)
    )
    assert result["error"] is None
    assert result["proven_optimal"]
    assert result["native_objective"] == min(feasible)


@pytest.mark.parametrize("waiting", [0, 2])
@pytest.mark.parametrize("objective", ["journey_time", "unserved"])
def test_fixed_k_matches_cp_and_tail_contract(waiting, objective):
    _, p = prepare_small(1, waiting=waiting)
    cp = (
        DddCpSatCapacityOptimizer
        if objective == "unserved"
        else DddIntegratedCpSatOptimizer
    )(DddIntegratedCpSatConfig(total_time_limit_seconds=5)).solve(p)
    result, plan = solve_native(
        p, NativeSolverConfig(objective=objective, time_limit=5)
    )
    assert result["error"] is None
    assert result["proven_optimal"]
    value = (
        cp["unserved_upper_bound"]
        if objective == "unserved"
        else round(cp.validated_upper_bound * T)
    )
    assert result["native_objective"] == value
    assert any(
        t.visits[-1].next_switch_time_seconds > 130 for t in plan.solution.trajectories
    )


def test_hints_are_not_fixes_and_reference_is_not_improvement():
    p = tiny()
    seed = DddReservoirCpPlan((), {})
    result, _plan = solve_native(p, NativeSolverConfig(time_limit=5), primal_seed=seed)
    assert result["reference_objective"] == 3 * T
    assert result["native_objective"] == 2 * T
    fixed, _ = solve_native(p, NativeSolverConfig(time_limit=5), fixed_plan=seed)
    assert fixed["native_objective"] == 3 * T
    assert fixed["proof_scope"] == "FIXED_MOVEMENT"
    assert not any(e.get("improves_reference") for e in fixed["events"])


def test_waiting_release_full_cabin_and_shared_resources():
    p = problem(available_fleet_count=2)
    p = replace(
        p,
        waiting_policy=replace(
            p.waiting_policy,
            maximum_wait_seconds_by_station_id=(("A", 2.0), ("B", 2.0)),
            step_seconds=1,
            earliest_wait_time_seconds=0,
            domain=__import__(
                "ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation",
                fromlist=["DddTrajectoryWaitingDomain"],
            ).DddTrajectoryWaitingDomain.BOUNDED_WAIT,
        ),
        dispatch_end_seconds=0,
        demand_groups=(EanDemandGroup("g", "A", "B", 1.5, 1),),
    )
    p = replace(
        p,
        movement_core=replace(
            p.movement_core, passenger_service_end_seconds=4, operational_end_seconds=5
        ),
    )
    result, plan = solve_native(p, NativeSolverConfig(time_limit=5))
    assert result["error"] is None
    assert result["proven_optimal"] and result["native_objective"] == 1500000
    assert any(w for t in plan.trips for w in t.wait_ticks)
    late = replace(
        p, waiting_policy=replace(p.waiting_policy, earliest_wait_time_seconds=2)
    )
    r, _ = solve_native(late, NativeSolverConfig(time_limit=5))
    assert r["proven_optimal"] and r["native_objective"] == 2500000


def test_return_node_collision_is_present_even_without_following_visit():
    p = tiny()
    p = replace(p, available_fleet_count=2, dispatch_end_seconds=4)
    p = replace(p, movement_core=replace(p.movement_core, operational_end_seconds=8))
    b = build_native_model(p)
    a, v = b.algebra, b.variables
    # First cabin returns to A at t=4; the second cannot dispatch at t=4.
    a.add(
        v["time", 0, 0] == 0,
        v["active", 0, 0],
        v["route", 0, 0, "A_stop"],
        v["route", 0, 1, "B_stop"],
        v["active", 0, 2] == False,
        v["active", 1, 0],
        v["time", 1, 0] == 4 * T,
    )
    assert str(a.engine.check()) == "unsat"


@pytest.mark.parametrize("horizon,expected", [(56.272727, True), (56.272726, False)])
def test_destination_cutoff_exactly_and_one_tick_later(horizon, expected):
    from test_optimization_ddd_cp_sat_integrated import tiny_problem

    _, p = tiny_problem(
        horizon=horizon, tail=70, groups=(EanDemandGroup("ab", "A", "B", 0, 1),)
    )
    _, larger = tiny_problem(groups=(EanDemandGroup("ab", "A", "B", 0, 1),))
    p = replace(
        p,
        passenger_build=replace(
            p.passenger_build, ride_candidates=larger.passenger_build.ride_candidates
        ),
    )
    b = build_native_model(p, objective="unserved")
    b.algebra.add(b.variables["ride", p.passenger_build.ride_candidates[0].id] == 1)
    assert (str(b.algebra.engine.check()) == "sat") == expected


def test_every_small_overtaking_timetable_retains_its_passenger_optimum():
    from test_optimization_ddd_cp_sat_integrated import fixed_ip, tiny_problem

    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
        validate_ddd_cp_sat_incumbent,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.models import DddRouteDecision
    from ropeway_skip_stop_optimization.optimization.ddd.reference import (
        DddReferenceSolution,
        DddReferenceTrajectoryGenerator,
        validate_ddd_reference_solution,
    )

    scenario, p = tiny_problem(horizon=80, starts=(0.0, 8.0))
    movement = p.resolved_trajectory_problem.structural_movement_problem
    generated = DddReferenceTrajectoryGenerator().generate(movement)
    overtaking = False
    for combo in product(*generated.by_cabin_id.values()):
        s = DddReferenceSolution(combo)
        try:
            validate_ddd_reference_solution(movement, s)
        except ValueError:
            continue
        expected, _ = fixed_ip(scenario, p, s)
        seed = validate_ddd_cp_sat_incumbent(p, s, {}, provenance="enumeration")
        r, _ = solve_native(p, NativeSolverConfig(time_limit=5), fixed_plan=seed)
        assert r["error"] is None and r["proven_optimal"]
        assert r["native_objective"] == round(expected * T)
        overtaking |= (
            combo[0].visits[0].decision is DddRouteDecision.STOP
            and combo[1].visits[0].decision is DddRouteDecision.SKIP
        )
    assert overtaking


def test_original_odd_cycle_assignment_stays_integer():
    import gurobipy as gp
    from test_optimization_ean_passenger_service import _odd_cycle_fixed_movement_case

    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_movement import (
        _deterministic_visit_structure,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.models import (
        DddFixedStart,
        DddMovementProblem,
        DddMovementState,
        DddResource,
        DddResourceUsage,
        DddRouteDecision,
        DddRouteOption,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.native_solvers.model import (
        PreparedNativeStructure,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import (
        DddTrajectoryWaitingPolicy,
    )
    from ropeway_skip_stop_optimization.optimization.ean import (
        EanPassengerCandidateBuilder,
        EanPassengerObjective,
    )
    from ropeway_skip_stop_optimization.optimization.ean.optimizers.fixed_movement_passenger_model import (
        EanFixedMovementPassengerModelBuilder,
        EanPassengerAssignmentDomain,
    )

    scenario, artifact, plan = _odd_cycle_fixed_movement_case()
    states = artifact.state_ids
    routes = tuple(
        DddRouteOption(
            id=f"{s}:{d.value}",
            from_state_id=s,
            to_state_id=states[(i + 1) % 3],
            station_id=str(i),
            decision=d,
            duration_seconds=1.0,
            platform_entry_offset_seconds=0.2 if d is DddRouteDecision.STOP else None,
            platform_exit_offset_seconds=0.5 if d is DddRouteDecision.STOP else None,
            exit_switch_offset_seconds=0.7,
            resource_usages=(DddResourceUsage(s, 0.0, 0.0),),
        )
        for i, s in enumerate(states)
        for d in DddRouteDecision
    )
    movement = DddMovementProblem(
        scenario_id=scenario.id,
        passenger_service_end_seconds=5.0,
        operational_end_seconds=5.0,
        states=tuple(DddMovementState(s) for s in states),
        route_options=routes,
        resources=tuple(DddResource(s, 0.1) for s in states),
        starts=tuple(
            DddFixedStart(s.cabin_id, s.first_switch_id, 0.0, 6)
            for s in artifact.cabin_starts
        ),
    )
    passengers = EanPassengerCandidateBuilder().build(scenario, artifact)
    prepared = PreparedNativeStructure(
        "fixed_k",
        movement,
        DddTrajectoryWaitingPolicy(),
        tuple(
            (s.cabin_id, _deterministic_visit_structure(movement, s.state_id, 6)[0])
            for s in movement.starts
        ),
        passengers.demand_groups,
        passengers.ride_candidates,
        1,
        (),
        6 * T,
        1,
        "{}",
        "odd_cycle_unit_fixture",
    )
    b = build_native_model(None, prepared=prepared)
    for t in plan.trajectories:
        for v in t.visits:
            for decision in DddRouteDecision:
                b.algebra.add(
                    b.variables[
                        "route",
                        t.cabin_id,
                        v.visit_index,
                        f"{v.switch_id}:{decision.value}",
                    ]
                    == (v.decision.value == decision.value)
                )
    assert str(b.algebra.engine.check()) == "sat"
    native = b.algebra.engine.model().eval(b.objective).as_long()
    with gp.Model() as model:
        model.Params.OutputFlag = 0
        model.Params.Threads = 1
        EanFixedMovementPassengerModelBuilder().build(
            model=model,
            scenario=scenario,
            artifact=artifact,
            movement_plan=plan,
            passenger_build=passengers,
            objective=EanPassengerObjective.JOURNEY_TIME,
            assignment_domain=EanPassengerAssignmentDomain.INTEGER,
            grb=gp.GRB,
            gp=gp,
        )
        model.optimize()
        assert model.Status == gp.GRB.OPTIMAL and native == round(model.ObjVal * T)


def test_large_integer_ticks_and_invalid_range():
    p = tiny()
    p = replace(
        p,
        movement_core=replace(p.movement_core, operational_end_seconds=3000),
        dispatch_start_seconds=2995,
        dispatch_end_seconds=2995,
    )
    r, _ = solve_native(p, NativeSolverConfig(objective="unserved", time_limit=5))
    assert r["proven_optimal"] and r["native_objective"] == 1
    p = replace(p, demand_groups=(EanDemandGroup("g", "A", "B", 0, 2**53),))
    with pytest.raises(ValueError, match="range"):
        prepare_native_structure(p)


def test_expired_build_budget_does_not_prove_infeasibility():
    r, _ = solve_native(tiny(), NativeSolverConfig(time_limit=1e-12))
    assert r["status"] == "TIMEOUT" and not r["proven_optimal"]
    assert r["lower_bound"] is None


def test_fingerprints_are_separate_and_objectives_have_no_extra_products():
    p = tiny()
    manifest = p.fingerprint
    b = build_native_model(p, objective="unserved")
    assert not any(k[0].startswith("alight") for k in b.variables)
    assert p.fingerprint == manifest == b.prepared.domain_fingerprint
    assert b.fingerprint != build_native_model(p).fingerprint


def test_waiting_extends_only_the_declared_resource_and_detects_conflict():
    from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (
        DddTrajectoryWaitingDomain,
    )

    p = tiny()
    routes = tuple(
        replace(
            o,
            resource_usages=tuple(
                replace(u, leader_clear_wait_coefficient=1) for u in o.resource_usages
            ),
        )
        if o.id == "A_stop"
        else o
        for o in p.movement_core.route_options
    )
    p = replace(
        p,
        available_fleet_count=2,
        movement_core=replace(
            p.movement_core, route_options=routes, operational_end_seconds=5
        ),
        waiting_policy=replace(
            p.waiting_policy,
            domain=DddTrajectoryWaitingDomain.BOUNDED_WAIT,
            step_seconds=1,
            maximum_wait_seconds_by_station_id=(("A", 1.0), ("B", 1.0)),
            earliest_wait_time_seconds=0,
        ),
    )
    b = build_native_model(p, objective="unserved")
    a, v = b.algebra, b.variables
    a.add(
        v["active", 0, 0],
        v["time", 0, 0] == 0,
        v["route", 0, 0, "A_stop"],
        v["wait", 0, 0] == 1,
        v["active", 1, 0],
        v["time", 1, 0] == T,
        v["route", 1, 0, "A_skip"],
    )
    assert str(a.engine.check()) == "unsat"


@pytest.mark.parametrize(
    "offset,headway,boundary_start,expected",
    [
        (1.0, 1.0, 2.0, True),
        (0.0, 1.0, 2.0, False),
        (2.0, 1.0, 2.5, False),
        (1.0, 3.0, 2.5, False),
    ],
)
def test_resource_entry_at_horizon_and_clearance_beyond(
    offset, headway, boundary_start, expected
):
    from test_optimization_ddd_cp_sat_passenger import _horizon_movement

    from ropeway_skip_stop_optimization.optimization.ddd.models import DddRouteDecision
    from ropeway_skip_stop_optimization.optimization.ddd.native_solvers.model import (
        PreparedNativeStructure,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.reference import (
        DddReferenceResourceOccurrence,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import (
        DddTrajectoryWaitingPolicy,
    )

    m = _horizon_movement(offset, headway)
    m = replace(
        m,
        route_options=(
            replace(
                m.route_options[0],
                decision=DddRouteDecision.STOP,
                platform_entry_offset_seconds=0.0,
                platform_exit_offset_seconds=0.0,
            ),
        ),
    )
    boundary = DddReferenceResourceOccurrence("r", 99, 0, 3.0, boundary_start, 1.0)
    p = PreparedNativeStructure(
        "fixed_k",
        m,
        DddTrajectoryWaitingPolicy(),
        ((0, ("A", "A", "A")),),
        (),
        (),
        1,
        (boundary,),
        4 * T,
        1,
        "{}",
        "horizon_unit",
    )
    b = build_native_model(None, prepared=p, objective="unserved")
    assert (str(b.algebra.engine.check()) == "sat") == expected
