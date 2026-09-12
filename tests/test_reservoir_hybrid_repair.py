from dataclasses import replace
from time import perf_counter

from ortools.sat.python import cp_model
import pytest

from test_reservoir_hybrid import small, enumerate_plans
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.repair import (
    ReservoirRepairProblem,
    ReservoirRepairOptimizer,
    build_repair,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (
    DddReservoirCpSatOptimizer,
    _movement_values,
    build_reservoir_cp_sat,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
    DddIntegratedCpSatConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    validate_reservoir_cp_plan,
)


@pytest.mark.parametrize("waiting", [False, True])
@pytest.mark.parametrize("presolve", [False, True])
def test_all_open_repair_matches_global_cp_and_closed_is_identity(waiting, presolve):
    p = small(waiting)
    seed = next(s for s in enumerate_plans(p) if s.ride_counts)
    global_result = DddReservoirCpSatOptimizer(
        DddIntegratedCpSatConfig(total_time_limit_seconds=5, num_workers=1)
    ).solve(p)
    context = ReservoirRepairProblem.prepare(p, seed, [0])
    plan, result = ReservoirRepairOptimizer().solve(
        context, time_limit=5, workers=1, presolve=presolve
    )
    assert result["status"] == "OPTIMAL"
    assert result["validated_upper_bound"] == global_result["validated_upper_bound"]
    assert result["native_solutions"] >= 1
    assert validate_reservoir_cp_plan(p, plan)
    closed = ReservoirRepairProblem.prepare(p, seed, [])
    same, stats = ReservoirRepairOptimizer().solve(closed)
    assert same == seed and stats["variables"] == 0


def test_outside_calendar_rejects_collision_and_canonicalizes_earlier_insert():
    p = replace(small(), available_fleet_count=2)
    one = next(s for s in enumerate_plans(p) if s.ride_counts)
    # Only one deployment is present; keep its passengers outside and insert another.
    context = ReservoirRepairProblem.prepare(p, one, [], 1)
    assert context.slots == 1 and not context.local_seed.trips
    assert context.local.demand_groups == ()
    built = build_repair(context, deadline=perf_counter() + 5)
    conflicting = DddReservoirCpPlan((replace(one.trips[0], cabin_id=0),), {})
    values = _movement_values(context.local, built, conflicting)
    for index, value in values.items():
        built.movement.model.add(
            built.movement.model.get_int_var_from_proto_index(index) == value
        )
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    assert solver.solve(built.movement.model) == cp_model.INFEASIBLE
    with pytest.raises(ValueError):
        context.assemble(conflicting)
    later = replace(
        one.trips[0],
        switch_ticks=tuple(t + 1_000_000 for t in one.trips[0].switch_ticks),
        return_tick=one.trips[0].return_tick + 1_000_000,
    )
    later_seed = DddReservoirCpPlan((later,), one.ride_counts)
    inserting = ReservoirRepairProblem.prepare(p, later_seed, [], 1)
    merged = inserting.assemble(conflicting)
    assert merged.trips[0].switch_ticks[0] < merged.trips[1].switch_ticks[0]
    served_rides = {r.id: r for r in p.passenger_build.ride_candidates}
    assert all(served_rides[rid].cabin_id == 1 for rid in merged.ride_counts)


def test_residual_demand_and_local_slots_release_only_open_passengers():
    p = replace(small(), available_fleet_count=4)
    seed = next(s for s in enumerate_plans(p) if s.ride_counts)
    context = ReservoirRepairProblem.prepare(p, seed, [0], 2)
    assert context.slots == 3
    assert context.local.demand_groups == p.demand_groups
    assert context.assemble(context.local_seed) == seed
    for bad in ([99], [0, 0]):
        with pytest.raises(ValueError):
            ReservoirRepairProblem.prepare(p, seed, bad)


def test_partial_repair_matches_independently_fixed_full_model():
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
        DddReservoirCpTrip,
    )

    p = small(False)
    p = replace(
        p,
        available_fleet_count=2,
        demand_groups=(replace(p.demand_groups[0], count=2),),
    )
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
    counts = {
        r.id: 1 for r in p.passenger_build.ride_candidates if r.board_visit_index == 0
    }
    seed = DddReservoirCpPlan(trips, counts)
    validate_reservoir_cp_plan(p, seed)
    context = ReservoirRepairProblem.prepare(p, seed, [1])
    candidate, result = ReservoirRepairOptimizer().solve(
        context, workers=1, time_limit=5
    )
    full = build_reservoir_cp_sat(p)
    values = _movement_values(p, full, seed)
    indices = {
        v.index
        for v in full.movement.time_by_cabin[0] + full.movement.active_by_cabin[0]
    }
    indices.update(
        v.index for (k, i), v in full.movement.wait_steps_by_key.items() if k == 0
    )
    indices.update(
        v.index for (k, i, oid), v in full.movement.selection_by_key.items() if k == 0
    )
    for index in indices:
        full.movement.model.add(
            full.movement.model.get_int_var_from_proto_index(index) == values[index]
        )
    for r in p.passenger_build.ride_candidates:
        if r.cabin_id == 0:
            full.movement.model.add(
                full.passengers.ride_count[r.id] == counts.get(r.id, 0)
            )
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    assert solver.solve(full.movement.model) == cp_model.OPTIMAL
    assert result["status"] == "OPTIMAL"
    assert abs(solver.objective_value / 1e6 - result["validated_upper_bound"]) < 1e-6
    assert validate_reservoir_cp_plan(p, candidate).served == 2
