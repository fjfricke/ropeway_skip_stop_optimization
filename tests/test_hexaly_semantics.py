"""Reuse independent native-model certificates for the now licensed engine.

Fixed-timetable passenger optima test semantics; cold search quality is recorded
separately by the bounded validation runs and is not relabeled as correctness.
"""

from dataclasses import replace

import pytest
import test_native_solvers as shared


@pytest.fixture(autouse=True)
def hexaly_backend(monkeypatch):
    hx = pytest.importorskip("hexaly.optimizer")
    try:
        with hx.HexalyOptimizer():
            pass
    except hx.HxError as exc:
        pytest.skip(f"Hexaly license unavailable: {exc}")
    original = shared.solve_native

    def solve(problem, config=None, **kwargs):
        config = shared.NativeSolverConfig() if config is None else config
        return original(problem, replace(config, backend="hexaly"), **kwargs)

    monkeypatch.setattr(shared, "solve_native", solve)


def test_all_independently_valid_overtaking_plans_keep_integer_passenger_optima():
    shared.test_every_small_overtaking_timetable_retains_its_passenger_optimum()


def test_timeout_cannot_prove_infeasibility():
    shared.test_expired_build_budget_does_not_prove_infeasibility()


@pytest.mark.parametrize("operation", ["fixed_k", "reservoir"])
@pytest.mark.parametrize("objective", ["journey_time", "unserved"])
def test_fixed_reference_and_free_seed_adoption(operation, objective):
    from ropeway_skip_stop_optimization.optimization.ddd.native_solvers import (
        solve_native,
    )

    p = (
        shared.tiny()
        if operation == "reservoir"
        else shared.prepare_small(1, waiting=2)[1]
    )
    expected, seed = solve_native(
        p, shared.NativeSolverConfig(objective=objective, time_limit=5)
    )
    replay, _ = shared.solve_native(
        p,
        shared.NativeSolverConfig(objective=objective, time_limit=5),
        fixed_plan=seed,
        fix_passengers=True,
    )
    assert replay["error"] is None and replay["proven_optimal"]
    assert replay["native_objective"] == expected["native_objective"]
    seeded, _ = shared.solve_native(
        p,
        shared.NativeSolverConfig(objective=objective, time_limit=5),
        primal_seed=seed,
    )
    assert seeded["error"] is None
    assert seeded["native_objective"] == expected["native_objective"]
    assert not any(e.get("improves_reference") for e in seeded["events"])


@pytest.mark.parametrize(
    "intervals,expected",
    [
        ([(True, 0, 2), (True, 2, 4)], True),
        ([(True, 0, 3), (True, 2, 4)], False),
        ([(True, 5, 7), (True, 0, 2), (True, 2, 5)], True),
        ([(False, 0, 100), (True, 1, 2)], True),
        ([(False, 0, 100)], True),
        ([(True, 2**31 + 1, 2**31 + 3), (True, 2**31 + 3, 2**31 + 5)], True),
    ],
)
def test_native_resource_lists_preserve_half_open_intervals_and_presence(
    intervals, expected
):
    from ropeway_skip_stop_optimization.optimization.ddd.native_solvers.model import (
        HexalyAlgebra,
    )

    a = HexalyAlgebra()
    try:
        a.resources({"r": intervals}, None)
        a.m.minimize(0)
        a.m.close()
        a.engine.param.time_limit = 1
        a.engine.param.verbosity = 0
        a.engine.solve()
        if expected:
            assert a.engine.solution.status in (
                a.hx.HxSolutionStatus.FEASIBLE,
                a.hx.HxSolutionStatus.OPTIMAL,
            )
        else:
            assert a.engine.solution.status == a.hx.HxSolutionStatus.INCONSISTENT
    finally:
        a.engine.delete()


@pytest.mark.parametrize(
    "release,horizon,quantity,expected",
    [
        (6.5, 15.0, 1, True),  # Release at actual exit, including origin waiting.
        (6.500001, 15.0, 1, False),
        (0.0, 8.0, 1, True),  # Destination arrival precedes destination waiting.
        (0.0, 7.999999, 1, False),
        (0.0, 15.0, 2, True),  # Full cabin.
        (0.0, 15.0, 3, False),
    ],
)
def test_fixed_waiting_service_guards_and_integer_capacity(
    release, horizon, quantity, expected
):
    from test_optimization_ddd_reservoir_arc_flow import _problem
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_problem import (
        DddReservoirCpSatProblem,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.native_solvers import (
        build_native_model,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.native_solvers.optimizer import (
        apply_start,
    )

    p = DddReservoirCpSatProblem.from_arc_flow(_problem(waiting=True, fleet=1))
    p = replace(
        p,
        cabin_capacity=2,
        demand_groups=(shared.EanDemandGroup("g", "A", "B", release, 3),),
        movement_core=replace(p.movement_core, passenger_service_end_seconds=horizon),
    )
    t = replace(
        shared.trip(dispatch=5),
        wait_ticks=(shared.T, shared.T),
        switch_ticks=(5 * shared.T, 8 * shared.T),
        return_tick=11 * shared.T,
    )
    ref = shared.DddReservoirCpPlan((t,), {})
    shared.validate_reservoir_cp_plan(p, ref)
    b = build_native_model(p, backend="hexaly", objective="unserved", fixed_plan=ref)
    a = b.algebra
    try:
        q = next(
            q
            for q in p.passenger_build.ride_candidates
            if q.board_visit_index == 0 and q.alight_visit_index == 1
        )
        assert b.variables["ride", q.id].is_int()
        a.m.open()
        a.add(b.variables["ride", q.id] == quantity)
        a.m.close()
        apply_start(p, b, ref)
        a.engine.param.time_limit = 2
        a.engine.param.nb_threads = 1
        a.engine.param.verbosity = 0
        a.engine.solve()
        if expected:
            assert a.engine.solution.status in (
                a.hx.HxSolutionStatus.FEASIBLE,
                a.hx.HxSolutionStatus.OPTIMAL,
            )
            assert b.variables["ride", q.id].value == quantity
        else:
            assert a.engine.solution.status == a.hx.HxSolutionStatus.INCONSISTENT
    finally:
        a.engine.delete()
