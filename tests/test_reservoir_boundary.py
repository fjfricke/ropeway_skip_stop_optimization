"""Exact port separation, lifecycle, encoding and checkpoint regression tests."""

import json
from dataclasses import asdict, replace
from itertools import product
from types import SimpleNamespace

import pytest
from ortools.sat.python import cp_model
from test_optimization_ddd_reservoir_cp_sat import T, problem, trip
from test_reservoir_capacity_phases import full_calendar, physical_small
from test_reservoir_lines import config

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    stable_fingerprint,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_boundary import (
    ReservoirBoundaryPolicy,
    apply_boundary_arguments,
    geometry_fingerprint,
    outward_tick,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    validate_reservoir_cp_plan,
    write_reservoir_cp_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_movement import (
    build_reservoir_cp_movement,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines import (
    ReservoirLineFormulation,
    ReservoirLineOptimizer,
    ReservoirLinePreparation,
    ReservoirLineVariant,
    prepare_line_problem,
    saturated_all_stop_reference,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.cp_model import (
    build_reservoir_line_model,
)


def shared(p, seconds=1):
    return replace(
        p,
        boundary_policy=ReservoirBoundaryPolicy(
            "port_A",
            p.entry_state_id,
            seconds,
            "synthetic exact test",
            geometry_fingerprint(p.movement_core),
        ),
    )


def port_only():
    p = problem(available_fleet_count=2)
    return replace(
        p,
        movement_core=replace(
            p.movement_core,
            route_options=tuple(
                replace(o, resource_usages=()) for o in p.movement_core.route_options
            ),
            resources=(),
        ),
    )


def fixed_status(p, plan, b=None):
    """Fix raw decisions without passing through the certificate checker."""
    b = b or build_reservoir_cp_movement(p, dispatch_order_symmetry=False)
    by_id = {t.cabin_id: t for t in plan.trips}
    for k, active in b.active_by_cabin.items():
        tr = by_id.get(k)
        n = len(tr.route_option_ids) if tr else 0
        for i, a in enumerate(active):
            b.model.add(a == int(i < n))
        if tr:
            for i, time in enumerate((*tr.switch_ticks, tr.return_tick)):
                b.model.add(b.time_by_cabin[k][i] == time)
            for i, (oid, w) in enumerate(zip(tr.route_option_ids, tr.wait_ticks)):
                b.model.add(b.selection_by_key[k, i, oid] == 1)
                b.model.add(b.wait_steps_by_key[k, i] == w // b.waiting_step_tick)
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.max_time_in_seconds = 2
    return solver.solve(b.model)


@pytest.mark.parametrize(
    "delta,valid", [(750000 - 1, False), (750000, True), (750000 + 1, True)]
)
def test_exact_gap_all_route_pairs(delta, valid):
    p = shared(port_only(), 0.75)
    for a, b in product(("stop", "skip"), repeat=2):
        # Complementary movements have identical round duration (3s).
        ra = (f"A_{a}", "B_skip" if a == "stop" else "B_stop")
        rb = (f"A_{b}", "B_skip" if b == "stop" else "B_stop")
        plan = DddReservoirCpPlan((trip(routes=ra), trip(1, delta / T, rb)), {})
        if valid:
            validate_reservoir_cp_plan(p, plan)
        else:
            with pytest.raises(ValueError, match="port/headway"):
                validate_reservoir_cp_plan(p, plan)
        assert (fixed_status(p, plan) == cp_model.OPTIMAL) == valid


@pytest.mark.parametrize("routes", [("A_stop", "B_stop"), ("A_stop", "B_stop") * 2])
def test_dispatch_against_return_or_circulating_passage(routes):
    p = shared(port_only())
    plan = DddReservoirCpPlan((trip(routes=routes), trip(1, 4.5)), {})
    # Dispatches are 4.5s apart; the first cabin's return/passage is only .5s away.
    with pytest.raises(ValueError, match="port/headway"):
        validate_reservoir_cp_plan(p, plan)
    assert fixed_status(p, plan) == cp_model.INFEASIBLE
    validate_reservoir_cp_plan(replace(p, boundary_policy=None), plan)


def test_empty_unused_and_terminal_at_horizon():
    p = shared(port_only())
    for plan in (
        DddReservoirCpPlan((), {}),
        DddReservoirCpPlan((trip(dispatch=0),), {}),
        DddReservoirCpPlan((trip(dispatch=16),), {}),
    ):
        # Widen dispatch only; geometry-bound evidence remains applicable.
        q = replace(p, dispatch_end_seconds=20)
        validate_reservoir_cp_plan(q, plan)
        assert fixed_status(q, plan) == cp_model.OPTIMAL
    b = build_reservoir_cp_movement(p)
    assert b.model.validate() == ""


def test_waiting_moves_port_passage_and_return():
    from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (
        DddTrajectoryWaitingDomain,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import (
        DddTrajectoryWaitingPolicy,
    )

    p = shared(port_only())
    p = replace(
        p,
        waiting_policy=DddTrajectoryWaitingPolicy(
            domain=DddTrajectoryWaitingDomain.BOUNDED_WAIT,
            step_seconds=0.5,
            maximum_wait_seconds_by_station_id=(("A", 1), ("B", 1)),
        ),
    )
    a = trip()
    waited = replace(a, switch_ticks=(0, 3 * T), wait_ticks=(T, 0), return_tick=5 * T)
    plan = DddReservoirCpPlan((waited, trip(1, 4.5)), {})
    with pytest.raises(ValueError, match="port/headway"):
        validate_reservoir_cp_plan(p, plan)
    assert fixed_status(p, plan) == cp_model.INFEASIBLE


def test_evidence_precision_hash_compatibility_and_roundtrip(tmp_path):
    p = problem()
    legacy = asdict(p)
    legacy.pop("boundary_policy")
    legacy.update(
        schema="single_use_reservoir_cp_domain_v1",
        boundary_contract="ideal_entry_state_no_depot_resource_unique_state_tick_v1",
        passenger_contract="direct_first_destination_empty_return_v1",
        derived_visit_count=len(p.visit_states) - 1,
    )
    assert p.fingerprint == stable_fingerprint(legacy)
    q = shared(p)
    assert q.fingerprint != p.fingerprint
    plan = DddReservoirCpPlan((trip(),), {})
    for i, domain in enumerate((p, q)):
        path = tmp_path / f"checkpoint{i}.json"
        write_reservoir_cp_checkpoint(path, domain, plan)
        loaded, replay = load_reference(path)
        assert loaded.problem.fingerprint == domain.fingerprint
        assert replay == plan
    assert outward_tick(1.000001) == 1_000_001
    assert outward_tick(1.00000101) == 1_000_002
    with pytest.raises(ValueError, match="different geometry"):
        replace(
            q,
            movement_core=replace(
                q.movement_core,
                route_options=tuple(
                    replace(o, duration_seconds=o.duration_seconds + 1)
                    for o in q.movement_core.route_options
                ),
            ),
        ).validate()
    with pytest.raises(ValueError, match="lacks rope-headway evidence"):
        apply_boundary_arguments(
            p, SimpleNamespace(reservoir_port_policy="shared_rope_headway")
        )
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps(asdict(q.boundary_policy)))
    assert (
        apply_boundary_arguments(
            p,
            SimpleNamespace(
                reservoir_port_policy="shared_rope_headway",
                port_headway_evidence=evidence,
            ),
        )
        == q
    )


@pytest.mark.parametrize(
    "formulation,variant",
    [
        (ReservoirLineFormulation.LEGACY_TEMPLATES, ReservoirLineVariant.INTERVALS),
        (
            ReservoirLineFormulation.LEGACY_TEMPLATES,
            ReservoirLineVariant.DISPATCH_DOMAINS,
        ),
        (ReservoirLineFormulation.SHARED_ROUNDS, ReservoirLineVariant.INTERVALS),
        (ReservoirLineFormulation.SHARED_RIDES, ReservoirLineVariant.INTERVALS),
    ],
)
def test_line_encodings_and_terminal_prefix(formulation, variant):
    p = shared(port_only(), 1.5)
    c = config(
        formulation=formulation,
        variant=variant,
        preparation=ReservoirLinePreparation.LEGACY_EAGER,
    )
    prepared = prepare_line_problem(p, c)
    for gap in (1, 1.5, 2):
        t0 = trip(routes=("A_stop", "B_stop") * 4)
        t1 = trip(1, gap, ("A_stop", "B_stop") * 4)
        plan = DddReservoirCpPlan((t0, t1), {})
        b = build_reservoir_line_model(p, prepared, c)
        chosen = next(
            t for t in prepared.templates if t.route_option_ids == t0.route_option_ids
        )
        for k, tr in enumerate(plan.trips):
            b.model.add(b.dispatch[k] == tr.switch_ticks[0])
            b.model.add(b.selection[k, chosen.id] == 1)
        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = 1
        solver.parameters.max_time_in_seconds = 2
        assert (solver.solve(b.model) == cp_model.OPTIMAL) == (gap >= 1.5)
    _result, plan = ReservoirLineOptimizer(c).solve(p)
    assert plan is not None
    validate_reservoir_cp_plan(p, plan)
    with pytest.raises(ValueError, match="different physical domain"):
        ReservoirLineOptimizer(c).solve(
            replace(p, boundary_policy=None), prepared=prepared
        )


def test_saturation_includes_boundary():
    p = problem()
    assert saturated_all_stop_reference(shared(p, 0.5)).saturated_cabins == 4
    assert saturated_all_stop_reference(shared(p, 1.5)).saturated_cabins == 2


def test_phase_network_exact_port_coverage_and_native_solution():
    from time import perf_counter

    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.model import (
        build_model,
        solve,
    )

    p = shared(physical_small(True), 0.75)
    net = full_calendar(p)
    for a in net.arcs:
        uses = [u for u in a.resources if u[0] == p.boundary_policy.resource_id]
        expected = a.source is not None and a.source[:2] == (p.entry_state_id, "entry")
        assert len(uses) == int(expected)
        if uses:
            assert uses[0][2] - uses[0][1] == 750000
    b = build_model(net)
    try:
        plan, _result = solve(b, deadline=perf_counter() + 5, threads=1)
        assert plan is not None
        validate_reservoir_cp_plan(p, plan)
        b.reference_values(plan)
    finally:
        b.model.dispose()


def test_unsupported_engines_reject_before_build():
    from ropeway_skip_stop_optimization.optimization.ddd.native_solvers.model import (
        prepare_native_structure,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_ibm_cp_model import (
        build_ddd_reservoir_ibm_cp,
    )

    p = shared(problem())
    with pytest.raises(ValueError, match="support shared_rope_headway"):
        prepare_native_structure(p)
    with pytest.raises(ValueError, match="support shared_rope_headway"):
        build_ddd_reservoir_ibm_cp(p)


def test_repair_protects_fixed_outside_return_against_local_dispatch():
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.repair import (
        ReservoirRepairProblem,
        build_repair,
    )

    p = shared(port_only())
    seed = DddReservoirCpPlan((trip(), trip(1, 6)), {})
    context = ReservoirRepairProblem.prepare(p, seed, (1,))
    built = build_repair(context)
    assert (
        fixed_status(
            context.local, DddReservoirCpPlan((trip(0, 4.5),), {}), built.movement
        )
        == cp_model.INFEASIBLE
    )


def test_legacy_all_stop_comparison_identity_is_unchanged():
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.bound import (
        comparison_fingerprint,
    )

    p = problem()
    old = asdict(p)
    old.pop("boundary_policy")
    old.pop("operating_mode")
    assert comparison_fingerprint(p) == stable_fingerprint(old)
    assert comparison_fingerprint(shared(p)) != comparison_fingerprint(p)


def test_phase_model_rejects_fixed_legacy_paths_with_too_small_port_gap():
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.model import (
        build_model,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.network import (
        replay_paths,
    )

    old = replace(physical_small(True), available_fleet_count=2)
    plan = DddReservoirCpPlan((trip(), trip(1, 1)), {})
    legacy_net = full_calendar(old)
    paths = replay_paths(legacy_net, plan)
    selected = {
        (a.source, a.target, a.kind, a.option_id)
        for path in paths.values()
        for a in path
    }
    new = shared(old, 1.5)
    built = build_model(full_calendar(new))
    try:
        for a in built.network.arcs:
            value = int((a.source, a.target, a.kind, a.option_id) in selected)
            built.x[a.id].LB = built.x[a.id].UB = value
        built.model.Params.Threads = 1
        built.model.Params.TimeLimit = 2
        built.model.optimize()
        assert (
            built.model.Status == 3
        )  # Native Gurobi infeasibility, no checker shortcut.
    finally:
        built.model.dispose()
