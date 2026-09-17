from dataclasses import replace
from itertools import product
import json

import pytest
from ortools.sat.python import cp_model

from test_optimization_ddd_reservoir_arc_flow import _problem
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
    DddIntegratedCpSatConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_passenger import (
    DddCpSatCostEncoding,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (
    DddReservoirCpSatOptimizer,
    DddReservoirCpObjective,
    build_reservoir_cp_sat,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_problem import (
    DddReservoirCpSatProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    DddReservoirCpTrip,
    validate_reservoir_cp_plan,
    reservoir_cp_plan_from_payload,
    read_reservoir_cp_checkpoint,
    read_reservoir_cp_checkpoint_for_fleet_resize,
    write_reservoir_cp_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup

T = 1_000_000


def problem(**kwargs):
    return replace(DddReservoirCpSatProblem.from_arc_flow(_problem(fleet=1)), **kwargs)


def trip(k=0, dispatch=0, routes=("A_stop", "B_stop")):
    # Tiny fixture: STOP takes 2 seconds, SKIP 1 second.
    times = []
    now = round(dispatch * T)
    for o in routes:
        times.append(now)
        now += (2 if o.endswith("stop") else 1) * T
    return DddReservoirCpTrip(k, tuple(routes), tuple(times), (0,) * len(routes), now)


@pytest.mark.parametrize("encoding", list(DddCpSatCostEncoding))
def test_exact_optimum_matches_independent_enumeration(encoding):
    p = problem(
        dispatch_end_seconds=3,
        dispatch_step_seconds=1,
        movement_core=replace(
            problem().movement_core,
            passenger_service_end_seconds=3,
            operational_end_seconds=4,
        ),
        demand_groups=(EanDemandGroup("g", "A", "B", 0, 1),),
    )
    # Independent exhaustive physical routes/dispatches and the one possible
    # passenger: resource use cannot conflict with itself on these short tours.
    costs = [3.0]
    for d in range(4):
        for n in (2, 4):
            for decisions in product(("stop", "skip"), repeat=n):
                routes = tuple(
                    f"{'A' if i % 2 == 0 else 'B'}_{x}" for i, x in enumerate(decisions)
                )
                t = trip(dispatch=d, routes=routes)
                if t.return_tick > 4 * T:
                    continue
                costs.append(3.0)
                for i in range(n - 1):
                    if routes[i] == "A_stop" and routes[i + 1] == "B_stop":
                        arrival = t.switch_ticks[i + 1] / T
                        if arrival <= 3:
                            costs.append(arrival)
    r = DddReservoirCpSatOptimizer(
        DddIntegratedCpSatConfig(total_time_limit_seconds=5, cost_encoding=encoding)
    ).solve(p)
    assert r["proven_optimal"] and r["validated_upper_bound"] == min(costs) == 2
    assert r["cp_lower_bound"] == 2


def test_dispatch_during_service_and_early_return_are_decisions():
    p = problem()
    r = DddReservoirCpSatOptimizer().solve(p)
    assert r["proven_optimal"] and r["validated_upper_bound"] == 1.5
    assert r["metrics"]["unserved"] == 0
    early = DddReservoirCpPlan((trip(dispatch=4.5),), {})
    assert early.trips[0].return_tick < p.resolved_core.passenger_service_end_tick
    fixed = DddReservoirCpSatOptimizer().solve(p, fixed_plan=early)
    assert fixed["validated_upper_bound"] == 1.5
    # Force dispatch after service begins; it remains possible and correctly priced.
    r2 = DddReservoirCpSatOptimizer().solve(replace(p, dispatch_start_seconds=6))
    assert r2["validated_upper_bound"] == 3


def test_continuous_service_uses_first_complete_return_after_deadline():
    p = problem(return_start_seconds=15)
    # Complete returns occur at seconds 4, 8, 12, 16, and 20.  Once the
    # lifecycle reaches the first return after the 15-second deadline, the
    # cabin must leave rather than run the discretionary fifth lap.
    late = DddReservoirCpPlan(
        (trip(routes=("A_stop", "B_stop") * 5),),
        {},
    )
    with pytest.raises(ValueError, match="first complete return"):
        validate_reservoir_cp_plan(p, late)

    result = DddReservoirCpSatOptimizer().solve(p)
    plan = reservoir_cp_plan_from_payload(result["plan"])
    assert result["proven_optimal"]
    validate_reservoir_cp_plan(p, plan)


def test_empty_operation_and_more_available_cabins_do_not_force_departures():
    p = problem(available_fleet_count=4)
    r = DddReservoirCpSatOptimizer().solve(p, fixed_plan=DddReservoirCpPlan((), {}))
    assert r["proven_optimal"] and r["metrics"]["used_fleet"] == 0
    assert r["metrics"]["unserved"] == 1 and r["proof_scope"] == "FIXED_MOVEMENT"


def test_minimum_active_fleet_forces_available_cabin_to_dispatch():
    p = problem()
    result = DddReservoirCpSatOptimizer().solve(p, minimum_active_fleet=1)
    assert result["minimum_active_fleet"] == 1
    assert result["metrics"]["used_fleet"] == 1
    with pytest.raises(ValueError, match="minimum active fleet"):
        DddReservoirCpSatOptimizer().solve(p, minimum_active_fleet=2)


def test_route_search_priority_only_adds_route_decision_strategy():
    p = problem()
    plain = build_reservoir_cp_sat(p)
    focused = build_reservoir_cp_sat(
        p,
        config=DddIntegratedCpSatConfig(route_search_priority=True),
    )
    assert len(plain.movement.model.proto.search_strategy) == 0
    assert len(focused.movement.model.proto.search_strategy) == 1
    strategy = focused.movement.model.proto.search_strategy[0]
    assert len(strategy.exprs) == len(focused.movement.selection_by_key)
    assert focused.stats["route_priority_literals"] == len(
        focused.movement.selection_by_key
    )


def test_no_return_at_other_station_or_after_horizon():
    p = problem()
    for t in (
        trip(routes=("A_stop",)),
        trip(dispatch=14, routes=("A_stop", "B_stop", "A_stop", "B_stop")),
    ):
        with pytest.raises(ValueError, match="return"):
            validate_reservoir_cp_plan(p, DddReservoirCpPlan((t,), {}))


def test_no_passenger_can_disappear_into_reservoir():
    p = problem(demand_groups=(EanDemandGroup("ba", "B", "A", 0, 1),))
    # B->A delivery requires an actual A STOP, not merely the boundary return.
    t = trip()
    candidate = next(
        q for q in p.passenger_build.ride_candidates if q.board_visit_index == 1
    )
    with pytest.raises(ValueError, match="empty|STOP"):
        validate_reservoir_cp_plan(p, DddReservoirCpPlan((t,), {candidate.id: 1}))
    r = DddReservoirCpSatOptimizer().solve(p, fixed_plan=DddReservoirCpPlan((t,), {}))
    assert r["metrics"]["unserved"] == 1


def test_unused_cabins_do_not_create_resources_but_used_ones_conflict():
    p = problem(available_fleet_count=2)
    t = trip()
    assert validate_reservoir_cp_plan(p, DddReservoirCpPlan((t,), {})).used_fleet == 1
    with pytest.raises(ValueError, match="headway|resource"):
        validate_reservoir_cp_plan(
            p, DddReservoirCpPlan((t, trip(k=1, dispatch=0.5)), {})
        )
    # Independent CP construction also rejects the resource collision.
    built = build_reservoir_cp_sat(p)
    m = built.movement
    for k, d in ((0, 0), (1, T // 2)):
        m.model.add(m.active_by_cabin[k][0] == 1)
        m.model.add(m.time_by_cabin[k][0] == d)
        for i, oid in enumerate(("A_stop", "B_stop")):
            m.model.add(m.selection_by_key[k, i, oid] == 1)
    solver = cp_model.CpSolver()
    assert solver.solve(m.model) == cp_model.INFEASIBLE


def test_return_does_not_remove_existing_protection_interval():
    p = problem(available_fleet_count=2)
    core = replace(
        p.movement_core,
        resources=tuple(
            replace(r, headway_seconds=5, maximum_headway_seconds=5)
            for r in p.movement_core.resources
        ),
    )
    p = replace(p, movement_core=core)
    # Cabin 0 returns at 4; its last protected rope_B use lasts until 7.
    with pytest.raises(ValueError, match="headway"):
        validate_reservoir_cp_plan(
            p, DddReservoirCpPlan((trip(), trip(k=1, dispatch=4.5)), {})
        )


def test_reuse_and_same_tick_boundary_merging_are_rejected():
    p = problem(available_fleet_count=2)
    with pytest.raises(ValueError, match="reused"):
        validate_reservoir_cp_plan(
            p, DddReservoirCpPlan((trip(), trip(dispatch=5)), {})
        )
    with pytest.raises(ValueError, match="state-time"):
        validate_reservoir_cp_plan(
            p, DddReservoirCpPlan((trip(), trip(k=1, dispatch=4)), {})
        )


def test_integer_capacity_and_release_are_checked_independently():
    p = problem(demand_groups=(EanDemandGroup("g", "A", "B", 0, 2),))
    q = next(q for q in p.passenger_build.ride_candidates if q.board_visit_index == 0)
    with pytest.raises(ValueError, match="capacity"):
        validate_reservoir_cp_plan(p, DddReservoirCpPlan((trip(),), {q.id: 2}))
    p2 = replace(p, demand_groups=(EanDemandGroup("g", "A", "B", 1, 1),))
    with pytest.raises(ValueError, match="release"):
        validate_reservoir_cp_plan(p2, DddReservoirCpPlan((trip(),), {q.id: 1}))


@pytest.mark.parametrize(
    "change",
    [
        {"available_fleet_count": 2},
        {"cabin_capacity": 2},
        {"dispatch_step_seconds": 1},
        {"return_start_seconds": 2},
    ],
)
def test_checkpoint_detects_changes_and_preserves_seed(tmp_path, change):
    p = problem()
    path = tmp_path / "seed.json"
    plan = DddReservoirCpPlan((trip(),), {})
    write_reservoir_cp_checkpoint(path, p, plan)
    assert read_reservoir_cp_checkpoint(path, p) == plan
    with pytest.raises(ValueError, match="fingerprint"):
        read_reservoir_cp_checkpoint(path, replace(p, **change))
    raw = json.loads(path.read_text())
    raw["plan"]["trips"][0]["return_tick"] += 1
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="return"):
        read_reservoir_cp_checkpoint(path, p)


def test_checkpoint_can_be_retargeted_only_across_fleet_caps(tmp_path):
    source = problem(available_fleet_count=2)
    plan = DddReservoirCpPlan((trip(),), {})
    path = tmp_path / "seed.json"
    write_reservoir_cp_checkpoint(path, source, plan)

    expanded = replace(source, available_fleet_count=4)
    contracted = replace(source, available_fleet_count=1)
    assert read_reservoir_cp_checkpoint_for_fleet_resize(path, expanded) == plan
    assert read_reservoir_cp_checkpoint_for_fleet_resize(path, contracted) == plan

    incompatible = replace(expanded, cabin_capacity=2)
    with pytest.raises(ValueError, match="more than the available-fleet cap"):
        read_reservoir_cp_checkpoint_for_fleet_resize(path, incompatible)


def test_timeout_keeps_validated_seed_without_claiming_optimality():
    p = problem()
    plan = DddReservoirCpPlan((trip(),), {})
    r = DddReservoirCpSatOptimizer(
        DddIntegratedCpSatConfig(total_time_limit_seconds=1e-9)
    ).solve(p, primal_seed=plan)
    assert r["solver_status"] == "UNKNOWN" and not r["proven_optimal"]
    assert r["cp_lower_bound"] is None and r["metrics"]["used_fleet"] == 1


def test_seed_can_supply_cutoff_without_becoming_a_solution_hint():
    p = problem()
    seed = DddReservoirCpPlan((trip(),), {})
    result = DddReservoirCpSatOptimizer(
        DddIntegratedCpSatConfig(total_time_limit_seconds=5)
    ).solve(p, primal_seed=seed, use_primal_hint=False)
    assert result["primal_hint_enabled"] is False
    assert result["proven_optimal"]
    assert result["metrics"]["unserved"] == 0


def test_solver_can_ignore_seed_hint_cutoff_and_lexicographic_cap():
    result = DddReservoirCpSatOptimizer(
        DddIntegratedCpSatConfig(total_time_limit_seconds=5),
        DddReservoirCpObjective.SERVICE_THEN_JOURNEY,
    ).solve(
        problem(),
        use_primal_hint=False,
        use_primal_cutoff=False,
        use_primal_lexicographic_cap=False,
    )
    assert result["primal_hint_enabled"] is False
    assert result["primal_cutoff_enabled"] is False
    assert result["primal_lexicographic_cap_enabled"] is False
    assert result["proven_optimal"]


def test_waiting_uses_same_resource_coefficients_and_bounds():
    p = DddReservoirCpSatProblem.from_arc_flow(_problem(waiting=True, fleet=1))
    t = trip(dispatch=5)
    waited = replace(
        t, wait_ticks=(T, 0), switch_ticks=(5 * T, 8 * T), return_tick=10 * T
    )
    validate_reservoir_cp_plan(p, DddReservoirCpPlan((waited,), {}))
    bad = replace(
        t, wait_ticks=(3 * T, 0), switch_ticks=(5 * T, 10 * T), return_tick=12 * T
    )
    with pytest.raises(ValueError, match="wait"):
        validate_reservoir_cp_plan(p, DddReservoirCpPlan((bad,), {}))
    r = DddReservoirCpSatOptimizer().solve(
        p, fixed_plan=DddReservoirCpPlan((waited,), {})
    )
    assert r["proven_optimal"] and r["metrics"]["unserved"] == 0


def test_unserved_objective_has_person_bounds_and_no_cost_products():
    r = DddReservoirCpSatOptimizer(objective=DddReservoirCpObjective.UNSERVED).solve(
        problem()
    )
    assert (
        r["proven_optimal"] and r["validated_upper_bound"] == r["cp_lower_bound"] == 0
    )
    assert r["bound_units"] == "persons" and r["model_stats"]["cost_auxiliaries"] == 0


def test_all_stop_plan_remains_feasible_in_skip_stop_domain():
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_arc_flow_problem import (
        DddReservoirOperatingMode,
    )
    from ropeway_skip_stop_optimization.benchmarking.ddd_reservoir_cp_sat import _plan

    p = problem()
    all_stop = replace(p, operating_mode=DddReservoirOperatingMode.ALL_STOP)
    reference = DddReservoirCpSatOptimizer().solve(all_stop)
    seed = _plan(reference["plan"])
    assert validate_reservoir_cp_plan(p, seed).unserved == 0
    result = DddReservoirCpSatOptimizer().solve(p, primal_seed=seed)
    assert result["validated_upper_bound"] <= reference["validated_upper_bound"]
    assert all_stop.fingerprint != p.fingerprint


def test_exit_wait_extends_resource_protection_in_validator_and_cp():
    p = DddReservoirCpSatProblem.from_arc_flow(_problem(waiting=True, fleet=2))
    core = replace(
        p.movement_core,
        route_options=tuple(
            replace(
                o,
                resource_usages=tuple(
                    replace(u, leader_clear_wait_coefficient=1)
                    for u in o.resource_usages
                ),
            )
            if o.id == "A_stop"
            else o
            for o in p.movement_core.route_options
        ),
    )
    p = replace(p, movement_core=core)
    first = DddReservoirCpTrip(
        0, ("A_stop", "B_stop"), (5 * T, 9 * T), (2 * T, 0), 11 * T
    )
    second = trip(k=1, dispatch=7, routes=("A_skip", "B_skip"))
    for t in (first, second):
        validate_reservoir_cp_plan(p, DddReservoirCpPlan((t,), {}))
    with pytest.raises(ValueError, match="headway"):
        validate_reservoir_cp_plan(p, DddReservoirCpPlan((first, second), {}))
    b = build_reservoir_cp_sat(p).movement
    for t in (first, second):
        k = t.cabin_id
        b.model.add(b.time_by_cabin[k][0] == t.switch_ticks[0])
        b.model.add(b.active_by_cabin[k][2] == 0)
        for i, oid in enumerate(t.route_option_ids):
            b.model.add(b.selection_by_key[k, i, oid] == 1)
            b.model.add(
                b.wait_steps_by_key[k, i] == t.wait_ticks[i] // b.waiting_step_tick
            )
    assert cp_model.CpSolver().solve(b.model) == cp_model.INFEASIBLE


def test_public_facade_exposes_reservoir_extension():
    from ropeway_skip_stop_optimization.optimization import ddd

    assert ddd.DddReservoirCpSatOptimizer is DddReservoirCpSatOptimizer
    assert ddd.DddReservoirCpSatProblem is DddReservoirCpSatProblem
    assert ddd.DddReservoirCpPlan is DddReservoirCpPlan
    assert ddd.validate_reservoir_cp_plan is validate_reservoir_cp_plan
    assert "DddReservoirCpSatOptimizer" in ddd.__all__
