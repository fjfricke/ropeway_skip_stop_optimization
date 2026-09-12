from dataclasses import replace
from time import perf_counter
import gurobipy as gp
import pytest

from test_reservoir_capacity_phases import physical_small
from test_reservoir_hybrid import enumerate_plans
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_arc_flow_problem import (
    DddReservoirOperatingMode,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.bound import (
    build_bound,
    solve_bound,
    certify_dual,
    comparison_fingerprint,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    validate_reservoir_cp_plan,
)


@pytest.mark.parametrize("waiting", [False, True])
def test_global_capacity_projection_and_exact_dual(waiting):
    p = physical_small(waiting)
    original = p
    p = replace(p, operating_mode=DddReservoirOperatingMode.ALL_STOP)
    assert comparison_fingerprint(p) == comparison_fingerprint(original)
    plans = [
        s
        for s in enumerate_plans(original)
        if all("skip" not in oid for tr in s.trips for oid in tr.route_option_ids)
    ]
    optimum = min(validate_reservoir_cp_plan(p, s).unserved for s in plans)
    for interval in (2_000_000, 1_000_000):
        b = build_bound(p, interval_tick=interval, parent_interval_tick=2_000_000)
        try:
            for s in plans:
                b.project(s)
            result = solve_bound(b, deadline=perf_counter() + 10, threads=1)
            assert result["dual_certificate"]
            assert result["global_lower_bound"] <= optimum
            assert b.objective == "unserved"
            assert not any(k[0] in ("t", "u") for k in b.variables)
        finally:
            b.model.dispose()


def test_dual_certificate_does_not_round_primal_objective():
    m = gp.Model()
    m.Params.OutputFlag = 0
    x = m.addVar(lb=0, ub=10)
    m.addConstr(3 * x >= 2)
    m.setObjective(x)
    m.optimize()
    try:
        cert = certify_dual(m)
        assert cert["integer_lower_bound"] == 1
        assert int(cert["numerator"]) * 3 <= int(cert["denominator"]) * 2
    finally:
        m.dispose()


def test_scope_rejected():
    with pytest.raises(ValueError, match="only all_stop"):
        build_bound(physical_small())
