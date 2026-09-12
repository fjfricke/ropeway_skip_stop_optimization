"""Native solver tests: execute only after the concurrent benchmark completes."""

from dataclasses import replace
from itertools import product
from time import perf_counter

import pytest

from test_reservoir_capacity_phases import physical_small, full_calendar
from test_reservoir_hybrid import enumerate_plans
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.formulation import (
    ReservoirPhaseFormulationConfig as Config,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.model import (
    build_model,
    solve,
    extract,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.network import (
    replay_paths,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    validate_reservoir_cp_plan,
)

CONFIGS = [Config()] + [
    Config(
        passenger_encoding=e,
        passenger_integrality=i,
        passenger_network=n,
        resource_encoding="maximal",
        conflict_cuts="local_cliques",
    )
    for e, i, n in product(
        ("legacy", "od_flow", "od_queue"), ("all", "boarding"), ("legacy", "contracted")
    )
]


@pytest.mark.parametrize("config", CONFIGS)
@pytest.mark.parametrize("waiting,release", [(False, 0), (True, 1.5), (True, 4)])
def test_all_formulations_match_independent_small_enumeration(config, waiting, release):
    p = physical_small(waiting, release)
    plans = list(enumerate_plans(p))
    optimum = min(validate_reservoir_cp_plan(p, plan).unserved for plan in plans)
    built = build_model(full_calendar(p), formulation=config)
    try:
        for plan in plans:
            built.reference_values(plan)
        plan, result = solve(built, deadline=perf_counter() + 10, threads=1)
        assert result["status"] == 2
        assert result["validated_upper_bound"] == optimum
        assert result["global_lower_bound"] is None
        assert validate_reservoir_cp_plan(p, plan).unserved == optimum
    finally:
        built.model.dispose()


def passenger_enumeration(p, movement):
    """Enumerate canonical quantities, independently of new passenger supports."""
    candidates = [
        r
        for r in p.passenger_build.ride_candidates
        if r.alight_visit_index < len(movement.trips[r.cabin_id].route_option_ids)
    ]
    best = None
    for quantities in product(
        *(
            range(
                min(
                    p.cabin_capacity,
                    next(g.count for g in p.demand_groups if g.id == r.demand_group_id),
                )
                + 1
            )
            for r in candidates
        )
    ):
        plan = DddReservoirCpPlan(
            movement.trips, {r.id: n for r, n in zip(candidates, quantities) if n}
        )
        try:
            metrics = validate_reservoir_cp_plan(p, plan)
        except ValueError:
            continue
        if best is None or metrics.unserved < best[0]:
            best = (metrics.unserved, plan)
    return best


@pytest.mark.parametrize("encoding", ("legacy", "od_flow", "od_queue"))
@pytest.mark.parametrize("integrality", ("all", "boarding"))
def test_multigroup_assignment_and_seed_projection(encoding, integrality):
    base = physical_small(waiting=True, release=0)
    movement = next(
        p
        for p in enumerate_plans(base)
        if len(p.trips) == 1 and len(p.trips[0].route_option_ids) == 2 and p.ride_counts
    )
    p = replace(
        base,
        cabin_capacity=2,
        demand_groups=(
            EanDemandGroup("early", "A", "B", 0, 2),
            EanDemandGroup("late", "A", "B", 0.5, 2),
        ),
    )
    optimum, seed = passenger_enumeration(p, movement)
    net = full_calendar(p)
    b = build_model(
        net,
        formulation=Config(
            passenger_encoding=encoding, passenger_integrality=integrality
        ),
        reference=seed,
    )
    try:
        values = b.reference_values(seed)
        paths = replay_paths(net, seed)
        used = {a.id for path in paths.values() for a in path}
        for aid, v in b.x.items():
            v.LB = v.UB = int(aid in used)
        plan, r = solve(b, deadline=perf_counter() + 10, threads=1, reference=seed)
        assert r["status"] == 2 and r["validated_upper_bound"] == optimum
        # A fully fixed reference has an exact lift; OD queue may choose a
        # different valid group decomposition with the same capacity value.
        decoded, metrics = extract(b, lambda v: values[v.index])
        assert metrics.unserved == optimum
        if encoding != "od_queue":
            assert decoded.ride_counts == seed.ride_counts
    finally:
        b.model.dispose()


def test_legacy_default_and_invalid_reference():
    p = physical_small()
    net = full_calendar(p)
    a = build_model(net)
    b = build_model(net, formulation=Config())
    try:
        assert a.fingerprint == b.fingerprint
        assert a.families == b.families
        with pytest.raises(ValueError):
            a.reference_values(DddReservoirCpPlan((), {"missing_positive_ride": 1}))
    finally:
        a.model.dispose()
        b.model.dispose()


def test_incomplete_seed_is_not_full_service_witness():
    p = physical_small(release=4)
    b = build_model(
        full_calendar(p),
        reference=DddReservoirCpPlan((), {}),
        require_full_service=True,
        formulation=Config(passenger_encoding="od_queue"),
    )
    try:
        _, r = solve(
            b,
            deadline=perf_counter() + 5,
            threads=1,
            reference=DddReservoirCpPlan((), {}),
        )
        assert r["status"] == 3
        assert r["validated_upper_bound"] == 1
        assert not r["global_optimal"]
    finally:
        b.model.dispose()


def test_legacy_algebra_matches_frozen_pre_refactor_builder():
    import importlib.util
    from pathlib import Path
    import sys

    source = (
        Path(__file__).resolve().parents[1]
        / "benchmarks/output/reservoir_capacity_followup_20260911_30min/sources/src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_capacity/model.py"
    )
    if not source.exists():
        pytest.skip("frozen private baseline not distributed")
    name = "ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity._frozen_baseline"
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    net = full_calendar(physical_small())
    old, new = module.build_model(net), build_model(net)

    def signature(model):
        rows = []
        for c in model.getConstrs():
            expr = model.getRow(c)
            terms = tuple(
                sorted(
                    (expr.getVar(i).VarName, expr.getCoeff(i))
                    for i in range(expr.size())
                )
            )
            rows.append((c.Sense, c.RHS, terms))
        variables = sorted(
            (v.VarName, v.LB, v.UB, v.VType, v.Obj) for v in model.getVars()
        )
        return variables, sorted(rows), model.ObjCon

    try:
        assert signature(old.model) == signature(new.model)
    finally:
        old.model.dispose()
        new.model.dispose()
        sys.modules.pop(name, None)
