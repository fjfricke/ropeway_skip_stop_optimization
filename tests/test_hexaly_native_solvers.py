"""Executable Hexaly gate; lack of a license is explicitly a skip, not a pass."""

import pytest
from test_native_solvers import tiny

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_didp import prepare_small
from ropeway_skip_stop_optimization.optimization.ddd.native_solvers import (
    NativeSolverConfig,
    solve_native,
)
from ropeway_skip_stop_optimization.optimization.ddd.native_solvers.optimizer import (
    validate_plan,
)


@pytest.fixture(scope="module", autouse=True)
def license_gate():
    hx = pytest.importorskip("hexaly.optimizer")
    try:
        with hx.HexalyOptimizer():
            pass
    except hx.HxError as exc:
        pytest.skip(f"Hexaly engine/license unavailable: {exc}")


@pytest.mark.parametrize("operation", ["fixed_k", "reservoir"])
@pytest.mark.parametrize("objective", ["journey_time", "unserved"])
def test_hexaly_cold_and_full_seed_replay(operation, objective):
    p = tiny() if operation == "reservoir" else prepare_small(1, waiting=2)[1]
    reference, seed = solve_native(
        p, NativeSolverConfig(objective=objective, time_limit=5)
    )
    assert reference["proven_optimal"]
    result, plan = solve_native(
        p, NativeSolverConfig(backend="hexaly", objective=objective, time_limit=5)
    )
    assert (
        result["error"] is None
        and result["native_objective"] == reference["native_objective"]
    )
    validate_plan(p, plan)
    replay, _ = solve_native(
        p,
        NativeSolverConfig(backend="hexaly", objective=objective, time_limit=5),
        fixed_plan=seed,
        fix_passengers=True,
    )
    assert (
        replay["error"] is None
        and replay["native_objective"] == reference["native_objective"]
    )
