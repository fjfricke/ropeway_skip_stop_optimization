"""Cross-engine domain checks; no large performance solves in this test suite."""

from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("docplex.cp")

from test_optimization_ddd_reservoir_cp_sat import problem, trip, T
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (
    DddReservoirCpSatOptimizer,
    DddReservoirCpObjective,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    read_reservoir_cp_checkpoint,
    validate_reservoir_cp_plan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_ibm_cp import (
    DddReservoirIbmCpConfig,
    DddReservoirIbmCpOptimizer,
    resolve_cp_optimizer,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_ibm_cp_model import (
    build_ddd_reservoir_ibm_cp,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_arc_flow_problem import (
    DddReservoirOperatingMode,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup


def short_problem(**kwargs):
    p = problem()
    return replace(
        p,
        dispatch_end_seconds=3,
        dispatch_step_seconds=1,
        movement_core=replace(
            p.movement_core, passenger_service_end_seconds=3, operational_end_seconds=4
        ),
        demand_groups=(EanDemandGroup("g", "A", "B", 0, 1),),
        **kwargs,
    )


@pytest.fixture
def engine():
    try:
        return Path(resolve_cp_optimizer())
    except FileNotFoundError:
        pytest.skip("IBM runtime not installed")


def optimizer(engine, **kwargs):
    return DddReservoirIbmCpOptimizer(
        DddReservoirIbmCpConfig(
            total_time_limit_seconds=5,
            executable=engine,
            log_search_progress=False,
            **kwargs,
        )
    )


@pytest.mark.parametrize("mode", list(DddReservoirOperatingMode))
def test_short_exact_optima_match_enumeration_and_cp_sat(engine, mode, tmp_path):
    p = short_problem(operating_mode=mode)
    r = optimizer(
        engine, checkpoint_path=tmp_path / "cp.json", export_path=tmp_path / "model.cpo"
    ).solve(p)
    cp = DddReservoirCpSatOptimizer().solve(p)
    assert r["error"] is None
    assert r["proven_optimal"] and cp["proven_optimal"]
    assert (
        r["validated_upper_bound"]
        == r["cp_lower_bound"]
        == cp["validated_upper_bound"]
        == 2
    )
    plan = read_reservoir_cp_checkpoint(tmp_path / "cp.json", p)
    assert validate_reservoir_cp_plan(p, plan).unserved == 0
    text = (tmp_path / "model.cpo").read_text()
    assert "noOverlap(" in text and "optional" in text
    assert r["problem_fingerprint"] == cp["problem_fingerprint"]


def test_fixed_movement_cost_and_seed_are_shared(engine, tmp_path):
    p = short_problem()
    fixed = DddReservoirCpPlan((trip(),), {})
    r = optimizer(engine, checkpoint_path=tmp_path / "ibm.json").solve(
        p, fixed_plan=fixed
    )
    assert r["proven_optimal"] and r["validated_upper_bound"] == 2
    seed = read_reservoir_cp_checkpoint(tmp_path / "ibm.json", p)
    cp = DddReservoirCpSatOptimizer().solve(p, primal_seed=seed)
    assert cp["validated_upper_bound"] == r["validated_upper_bound"]
    assert r["proof_scope"] == "FIXED_MOVEMENT"


def test_unused_fleet_and_empty_return(engine):
    p = short_problem(available_fleet_count=2)
    r = optimizer(engine).solve(p, fixed_plan=DddReservoirCpPlan((), {}))
    assert r["metrics"]["used_fleet"] == 0 and r["metrics"]["unserved"] == 1
    p = replace(short_problem(), demand_groups=(EanDemandGroup("ba", "B", "A", 0, 1),))
    r = optimizer(engine).solve(p, fixed_plan=DddReservoirCpPlan((trip(),), {}))
    assert r["metrics"]["unserved"] == 1 and r["validated_upper_bound"] == 3


def test_unserved_bounds_use_persons(engine):
    o = replace(optimizer(engine), objective=DddReservoirCpObjective.UNSERVED)
    r = o.solve(short_problem())
    assert (
        r["proven_optimal"] and r["validated_upper_bound"] == r["cp_lower_bound"] == 0
    )
    assert r["bound_units"] == "persons"


def test_cp_sat_seed_is_only_hint_and_does_not_fix_passengers(engine):
    p = short_problem()
    empty = DddReservoirCpPlan((trip(),), {})
    r = optimizer(engine).solve(p, primal_seed=empty)
    assert r["metrics"]["served"] == 1 and r["validated_upper_bound"] == 2


def test_invalid_seed_fails_before_native_search(engine):
    p = short_problem()
    t = replace(trip(), return_tick=5 * T)
    with pytest.raises(ValueError, match="return"):
        optimizer(engine).solve(p, primal_seed=DddReservoirCpPlan((t,), {}))


def test_deadline_preserves_verified_seed_without_bound():
    p = short_problem()
    seed = DddReservoirCpPlan((trip(),), {})
    r = DddReservoirIbmCpOptimizer(
        DddReservoirIbmCpConfig(total_time_limit_seconds=1e-9)
    ).solve(p, primal_seed=seed)
    assert r["solver_status"] == "UNKNOWN" and r["cp_lower_bound"] is None
    assert r["metrics"]["used_fleet"] == 1 and not r["proven_optimal"]


def test_missing_engine_is_error_not_claimed_solve(tmp_path):
    r = optimizer(tmp_path / "missing").solve(short_problem())
    assert (
        r["solver_status"] == "ERROR"
        and r["termination_reason"] == "ENGINE_UNAVAILABLE"
    )
    assert r["cp_lower_bound"] is None and not r["proven_optimal"]


def test_exact_ticks_are_retained_beyond_32_bit_range():
    p = short_problem()
    # Keep the same number of visits, but exceed the old 32-bit interval range.
    core = replace(
        p.movement_core,
        operational_end_seconds=4000,
        passenger_service_end_seconds=3999,
        route_options=tuple(
            replace(o, duration_seconds=o.duration_seconds * 1000)
            for o in p.movement_core.route_options
        ),
    )
    p = replace(p, movement_core=core, dispatch_end_seconds=3999)
    b = build_ddd_reservoir_ibm_cp(p)
    assert b.times[0][0].get_domain_max() == 4_000_000_000
    assert b.wait_step == 1  # one microsecond, never coarsened
