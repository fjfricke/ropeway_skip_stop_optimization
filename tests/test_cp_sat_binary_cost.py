from dataclasses import replace

import pytest
from ortools.sat.python import cp_model
from test_optimization_ddd_reservoir_arc_flow import _problem
from test_optimization_ddd_reservoir_cp_sat import trip

from ropeway_skip_stop_optimization.optimization.ddd.cp_formulation import (
    DddCpFormulationConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
    DddIntegratedCpSatConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_passenger import (
    DddCpSatCostEncoding,
    binary_count_time_product,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (
    DddReservoirCpObjective,
    DddReservoirCpSatOptimizer,
    _movement_values,
    build_reservoir_cp_sat,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_problem import (
    DddReservoirCpSatProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.route_topology import (
    unique_stop_route_option,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_seconds_to_tick,
)


@pytest.mark.parametrize("capacity", [0, 1, 2, 3, 4, 7, 8, 10])
@pytest.mark.parametrize("base", [0, 2**31 + 17])
def test_binary_product_exhaustive_projection(capacity, base):
    model = cp_model.CpModel()
    n = model.new_int_var(0, capacity, "n")
    t = model.new_int_var(base, base + 2, "t")
    value, bits = binary_count_time_product(model, n, t, capacity, base + 2, "test")
    assert len(bits) == capacity.bit_length()
    assert not any(c.has_int_prod() for c in model.proto.constraints)
    seen = set()

    class Check(cp_model.CpSolverSolutionCallback):
        def on_solution_callback(self):
            pair = self.value(n), self.value(t)
            assert self.value(value) == pair[0] * pair[1]
            assert pair not in seen  # Unique bit representation, no auxiliary symmetry.
            seen.add(pair)

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.enumerate_all_solutions = True
    assert solver.solve(model, Check()) == cp_model.OPTIMAL
    assert seen == {(n, t) for n in range(capacity + 1) for t in range(base, base + 3)}


@pytest.mark.parametrize("profile", ["legacy", "hints", "strengthened"])
def test_binary_waiting_reference_hints_and_no_capacity_costs(profile):
    p = DddReservoirCpSatProblem.from_arc_flow(_problem(waiting=True, fleet=1))
    t = replace(
        trip(dispatch=5),
        wait_ticks=(1_000_000, 0),
        switch_ticks=(5_000_000, 8_000_000),
        return_tick=10_000_000,
    )
    fixed = DddReservoirCpPlan((t,), {})
    baseline = DddReservoirCpSatOptimizer().solve(p, fixed_plan=fixed)
    counts = baseline["plan"]["ride_counts"]
    ref = DddReservoirCpPlan((t,), counts)
    config = DddIntegratedCpSatConfig(
        total_time_limit_seconds=5,
        num_workers=1,
        cost_encoding=DddCpSatCostEncoding.BINARY,
        formulation=DddCpFormulationConfig(profile=profile),
    )
    result = DddReservoirCpSatOptimizer(config).solve(
        p, fixed_plan=ref, primal_seed=ref
    )
    assert result["proven_optimal"]
    assert result["validated_upper_bound"] == baseline["validated_upper_bound"]
    b = build_reservoir_cp_sat(p, config=config)
    movement_values = _movement_values(p, b, ref)
    times = {
        (k, i): movement_values[b.movement.time_by_cabin[k][i].index]
        + ddd_seconds_to_tick(
            unique_stop_route_option(
                p.movement, state, error_context="test hint"
            ).platform_entry_offset_seconds
        )
        for k, states in b.movement.states_by_cabin.items()
        for i, state in enumerate(states[:-1])
    }
    b.passengers.add_hints(p, b.movement.model, counts, times)
    hint = b.movement.model.proto.solution_hint
    assert len(set(hint.vars)) == len(hint.vars)
    hint_values = dict(zip(hint.vars, hint.values))
    for (k, i, bit), (flag, value) in b.passengers.binary.items():
        n = hint_values[b.passengers.alight_count[k, i].index]
        assert hint_values[flag.index] == (n >> bit) & 1
        assert hint_values[value.index] == (times[k, i] if (n >> bit) & 1 else 0)
    capacity = build_reservoir_cp_sat(
        p, config=config, objective=DddReservoirCpObjective.UNSERVED
    )
    assert not capacity.passengers.binary
    assert capacity.stats["cost_auxiliaries"] == 0
    assert b.fingerprint != build_reservoir_cp_sat(p).fingerprint
