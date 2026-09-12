import pytest
from ortools.sat.python import cp_model
from test_optimization_ddd_reservoir_cp_sat import problem, trip

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
    DddIntegratedCpSatConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (
    DddReservoirCpSatOptimizer,
    _movement_values,
    build_reservoir_cp_sat,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_diagnostics import (
    ALL_PROFILES,
    ReservoirDiagnostic,
)


@pytest.mark.parametrize("profile", ALL_PROFILES)
def test_restrictions_retain_fixed_reference_and_scoped_optimum(profile):
    p = problem()
    ref = DddReservoirCpPlan((trip(),), {})
    b = build_reservoir_cp_sat(p)
    diagnostic = ReservoirDiagnostic(profile)
    info = diagnostic.apply(p, b, ref)
    for i, value in _movement_values(p, b, ref).items():
        b.movement.model.add(b.movement.model.get_int_var_from_proto_index(i) == value)
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.max_time_in_seconds = 2
    assert solver.solve(b.movement.model) == cp_model.OPTIMAL
    diagnostic.validate(p, ref, ref)
    result = DddReservoirCpSatOptimizer(
        DddIntegratedCpSatConfig(total_time_limit_seconds=3, num_workers=1)
    ).solve(p, primal_seed=ref, diagnostic=diagnostic)
    assert result["proven_optimal"]
    assert result["proof_scope"] == info["proof_scope"]
    assert result["model_stats"]["diagnostic"]["profile"] == profile


def test_fleet_only_allows_different_return_but_structure_does_not():
    p = problem()
    ref = DddReservoirCpPlan(
        (trip(routes=("A_stop", "B_stop", "A_stop", "B_stop")),), {}
    )
    shorter = DddReservoirCpPlan((trip(),), {})
    ReservoirDiagnostic("lifecycle").validate(p, ref, shorter)
    with pytest.raises(ValueError, match="lifecycle"):
        ReservoirDiagnostic("routes").validate(p, ref, shorter)


def test_timing_does_not_pin_time_or_wait_variables():
    p = problem()
    b = build_reservoir_cp_sat(p)
    ref = DddReservoirCpPlan((trip(),), {})
    old = len(b.movement.model.proto.constraints)
    ReservoirDiagnostic("timing").apply(p, b, ref)
    indices = {
        i for c in list(b.movement.model.proto.constraints)[old:] for i in c.linear.vars
    }
    assert not indices.intersection(
        v.index for xs in b.movement.time_by_cabin.values() for v in xs
    )
    assert not indices.intersection(
        v.index for v in b.movement.wait_steps_by_key.values()
    )


def test_order_check_rejects_reversal_even_when_physically_feasible():
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
        DddReservoirCpTrip,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (
        DddTrajectoryWaitingDomain,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import (
        DddTrajectoryWaitingPolicy,
    )

    p = problem(
        available_fleet_count=2,
        dispatch_end_seconds=8,
        waiting_policy=DddTrajectoryWaitingPolicy(
            domain=DddTrajectoryWaitingDomain.BOUNDED_WAIT,
            step_seconds=1,
            maximum_wait_seconds_by_station_id=(("A", 2), ("B", 2)),
        ),
    )
    ref = DddReservoirCpPlan((trip(0, 0), trip(1, 1)), {})
    delayed = DddReservoirCpTrip(
        0, ("A_stop", "B_stop"), (0, 4_000_000), (2_000_000, 0), 6_000_000
    )
    found = DddReservoirCpPlan((delayed, trip(1, 1)), {})
    ReservoirDiagnostic("timing").validate(p, ref, found)
    with pytest.raises(ValueError, match="resource order"):
        ReservoirDiagnostic("timing_order").validate(p, ref, found)
    built = build_reservoir_cp_sat(p)
    ReservoirDiagnostic("timing_order").apply(p, built, ref)
    for i, value in _movement_values(p, built, found).items():
        built.movement.model.add(
            built.movement.model.get_int_var_from_proto_index(i) == value
        )
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    assert solver.solve(built.movement.model) == cp_model.INFEASIBLE


def test_rejects_ambiguous_fixed_plan_and_diagnostic():
    p = problem()
    ref = DddReservoirCpPlan((trip(),), {})
    with pytest.raises(ValueError, match="diagnostic"):
        DddReservoirCpSatOptimizer().solve(
            p, primal_seed=ref, fixed_plan=ref, diagnostic=ReservoirDiagnostic("timing")
        )


def test_assignment_restriction_rejects_changed_quantities():
    from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup

    p = problem(demand_groups=(EanDemandGroup("early", "A", "B", 0, 1),))
    q = next(
        q
        for q in p.passenger_build.ride_candidates
        if q.cabin_id == 0 and q.board_visit_index == 0 and q.alight_visit_index == 1
    )
    ref = DddReservoirCpPlan((trip(),), {q.id: 1})
    changed = DddReservoirCpPlan(ref.trips, {})
    ReservoirDiagnostic("timing").validate(p, ref, changed)
    diagnostic = ReservoirDiagnostic("timing_assignment")
    with pytest.raises(ValueError, match="passenger assignment"):
        diagnostic.validate(p, ref, changed)
    built = build_reservoir_cp_sat(p)
    diagnostic.apply(p, built, ref)
    built.movement.model.add(built.passengers.ride_count[q.id] == 0)
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    assert solver.solve(built.movement.model) == cp_model.INFEASIBLE
