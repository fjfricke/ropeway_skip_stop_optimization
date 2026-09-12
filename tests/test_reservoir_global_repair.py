from dataclasses import replace

import pytest
from ortools.sat.python import cp_model
from test_reservoir_hybrid import small, enumerate_plans
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.global_repair import (
    GlobalPassengerRepair,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.repair import (
    ReservoirRepairProblem,
    ReservoirRepairOptimizer,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    DddReservoirCpTrip,
    validate_reservoir_cp_plan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (
    DddReservoirCpSatOptimizer,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
    DddIntegratedCpSatConfig,
)


@pytest.mark.parametrize("waiting", [False, True])
def test_all_open_matches_original(waiting):
    p = small(waiting)
    seed = next(s for s in enumerate_plans(p) if s.ride_counts)
    repair = GlobalPassengerRepair(ReservoirRepairProblem.prepare(p, seed, [0]))
    plan, result = repair.solve(time_limit=5, workers=1)
    full = DddReservoirCpSatOptimizer(
        DddIntegratedCpSatConfig(total_time_limit_seconds=5, num_workers=1)
    ).solve(p)
    assert result["status"] == "OPTIMAL"
    assert result["validated_upper_bound"] == full["validated_upper_bound"]
    validate_reservoir_cp_plan(p, plan)


def transfer_fixture():
    p = replace(small(False), available_fleet_count=2)
    trips = tuple(
        DddReservoirCpTrip(
            k,
            ("A_stop", "B_stop"),
            (k * 1000000, (k + 2) * 1000000),
            (0, 0),
            (k + 4) * 1000000,
        )
        for k in range(2)
    )
    ride = next(
        r
        for r in p.passenger_build.ride_candidates
        if r.cabin_id == 1 and r.board_visit_index == 0
    )
    return p, DddReservoirCpPlan(trips, {ride.id: 1})


def test_fixed_outside_passenger_can_move_to_open_trip():
    p, seed = transfer_fixture()
    context = ReservoirRepairProblem.prepare(p, seed, [0])
    old, old_result = ReservoirRepairOptimizer().solve(context, time_limit=5, workers=1)
    repair = GlobalPassengerRepair(context)
    built, virtual, values = repair.build()
    # Fix open times too: isolate passenger reassignment from movement changes.
    for index, value in values.items():
        built.movement.model.add(
            built.movement.model.get_int_var_from_proto_index(index) == value
        )
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    assert solver.solve(built.movement.model) == cp_model.OPTIMAL
    candidate = repair.extract(built, virtual, solver.value)
    assert (
        validate_reservoir_cp_plan(p, candidate).journey_time_tick
        < validate_reservoir_cp_plan(p, old).journey_time_tick
    )
    assert candidate.trips == seed.trips
    # Compare to independent original builder with every movement fixed.
    full = DddReservoirCpSatOptimizer(
        DddIntegratedCpSatConfig(total_time_limit_seconds=5, num_workers=1)
    ).solve(p, fixed_plan=seed)
    assert (
        validate_reservoir_cp_plan(p, candidate).journey_time_tick / 1e6
        == full["validated_upper_bound"]
    )


def test_late_fixed_boarding_is_not_reintroduced_and_all_hints_are_unique():
    p, seed = transfer_fixture()
    p = replace(p, demand_groups=(replace(p.demand_groups[0], release_time_seconds=2),))
    seed = DddReservoirCpPlan(seed.trips, {})
    repair = GlobalPassengerRepair(ReservoirRepairProblem.prepare(p, seed, [1]))
    built, virtual, _ = repair.build()
    indices = list(built.movement.model.proto.solution_hint.vars)
    assert len(indices) == len(set(indices))
    assert not built.movement.model.validate()
    # Outside cabin's fixed platform departure is 1s; release is 2s.
    assert all(
        r.cabin_id == 0
        for r in virtual.passenger_build.ride_candidates
        if r.id in built.passengers.ride_count
    )


def test_all_closed_keeps_movements_but_can_reassign_passengers():
    p, seed = transfer_fixture()
    plan, result = GlobalPassengerRepair(
        ReservoirRepairProblem.prepare(p, seed, [])
    ).solve(time_limit=5, workers=1)
    assert result["status"] == "OPTIMAL"
    assert plan.trips == seed.trips
    assert (
        validate_reservoir_cp_plan(p, plan).journey_time_tick
        < validate_reservoir_cp_plan(p, seed).journey_time_tick
    )


def test_new_slot_can_precede_fixed_outside_without_losing_its_riders():
    p, seed = transfer_fixture()
    seed = DddReservoirCpPlan(
        (replace(seed.trips[1], cabin_id=0),),
        {
            r.id: 1
            for r in p.passenger_build.ride_candidates
            if r.cabin_id == 0 and r.board_visit_index == 0
        },
    )
    plan, result = GlobalPassengerRepair(
        ReservoirRepairProblem.prepare(p, seed, [], 1)
    ).solve(time_limit=5, workers=1)
    assert result["status"] == "OPTIMAL"
    assert len(plan.trips) == 2
    assert plan.trips[0].switch_ticks[0] < plan.trips[1].switch_ticks[0]
    assert validate_reservoir_cp_plan(p, plan).served == 1


def test_conflicts_keep_late_reservations_and_protected_endpoints():
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.conflict_neighborhoods import (
        TimedUse,
        conflicts,
    )

    calendar = [TimedUse("r", 10, 20, 1, 2), TimedUse("r", 25, 30, 2, 0)]
    proposal = [TimedUse("r", 18, 25, 0, 1)]
    edges = conflicts(proposal, calendar)
    assert len(edges) == 1 and edges[0][1].cabin == 1
    assert not conflicts([TimedUse("r", 20, 25, 0, 1)], calendar)
    assert not conflicts([TimedUse("other", 18, 25, 0, 1)], calendar)


def test_selector_finds_actual_blocker_of_occupied_skip():
    from test_optimization_ddd_reservoir_arc_flow import _option
    from ropeway_skip_stop_optimization.optimization.ddd.models import (
        DddMovementState,
        DddResource,
        DddRouteDecision,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.conflict_neighborhoods import (
        select_conflict_neighborhoods,
    )

    p = small(False)
    p = replace(
        p,
        available_fleet_count=2,
        demand_groups=(replace(p.demand_groups[0], destination_station_id="C"),),
        movement_core=replace(
            p.movement_core,
            passenger_service_end_seconds=8,
            operational_end_seconds=10,
            states=tuple(DddMovementState(s) for s in "ABC"),
            resources=tuple(
                DddResource(f"rope_{s}", headway_seconds=2) for s in "ABC"
            ),
            route_options=tuple(
                _option(s, t, d, 2 if d is DddRouteDecision.STOP else 1)
                for s, t in zip("ABC", "BCA")
                for d in DddRouteDecision
            ),
        ),
    )
    trips = tuple(
        DddReservoirCpTrip(
            k,
            ("A_stop", "B_stop", "C_stop"),
            tuple((2 * i + 2 * k) * 1000000 for i in range(3)),
            (0, 0, 0),
            (6 + 2 * k) * 1000000,
        )
        for k in range(2)
    )
    ride = next(
        r
        for r in p.passenger_build.ride_candidates
        if r.cabin_id == 1 and r.board_visit_index == 0
    )
    seed = DddReservoirCpPlan(trips, {ride.id: 1})
    validate_reservoir_cp_plan(p, seed)
    selected = select_conflict_neighborhoods(p, seed)["neighborhoods"]
    assert len(selected) == 1
    assert selected[0]["anchor"] == 1 and selected[0]["skip_visit"] == 1
    assert selected[0]["open_ids"] == [0, 1]
    assert any(
        e["resource"] == "resource:rope_C" and e["overlap_tick"] == 1000000
        for e in selected[0]["conflicts"]
    )
