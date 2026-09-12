from dataclasses import replace
from itertools import product
from time import perf_counter

import pytest

from test_optimization_ddd_reservoir_arc_flow import _problem
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_problem import (
    DddReservoirCpSatProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    DddReservoirCpTrip,
    validate_reservoir_cp_plan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (
    DddReservoirCpSatOptimizer,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
    DddIntegratedCpSatConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.arrival_curves import (
    ArrivalIntervalPartition,
    ArrivalCurveEvaluator,
    arrivals,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.bound_domain import (
    TimeRegion,
    BoundArc,
    minimum_overlap,
    prepare_bound,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.bound_model import (
    ReservoirArrivalBoundBuilder,
    ReservoirArrivalBoundOptimizer,
    BoundSizeLimit,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.certificates import (
    ReservoirCertificateLedger,
    GlobalReservoirBound,
    LocalRepairResult,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    ReservoirOperatingDomain,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup

T = 1_000_000


def small(waiting=True, release=0):
    p = DddReservoirCpSatProblem.from_arc_flow(_problem(waiting=waiting, fleet=1))
    return replace(
        p,
        movement_core=replace(
            p.movement_core, passenger_service_end_seconds=4, operational_end_seconds=6
        ),
        dispatch_start_seconds=0,
        dispatch_end_seconds=2,
        waiting_policy=replace(p.waiting_policy, earliest_wait_time_seconds=0),
        demand_groups=(EanDemandGroup("g", "A", "B", release, 1),),
    )


def enumerate_plans(p):
    """Independent finite route/wait/assignment enumeration, no bound builder."""
    options = {o.id: o for o in p.resolved_core.route_options}
    yield DddReservoirCpPlan((), {})
    for dispatch in range(3):
        for n in (2, 4, 6):
            for decisions in product(("stop", "skip"), repeat=n):
                ids = tuple(
                    f"{'A' if i % 2 == 0 else 'B'}_{d}" for i, d in enumerate(decisions)
                )
                wait_options = [
                    (0, 1, 2)
                    if p.waiting_policy.maximum_wait_seconds("A") and d == "stop"
                    else (0,)
                    for d in decisions
                ]
                for ws in product(*wait_options):
                    time, times = dispatch * T, []
                    for oid, w in zip(ids, ws):
                        times.append(time)
                        time += options[oid].duration_tick + w * T
                    if time > 6 * T:
                        continue
                    tr = DddReservoirCpTrip(
                        0, ids, tuple(times), tuple(w * T for w in ws), time
                    )
                    for counts in (
                        {},
                        *(
                            {r.id: 1}
                            for r in p.passenger_build.ride_candidates
                            if r.alight_visit_index < n
                        ),
                    ):
                        plan = DddReservoirCpPlan((tr,), counts)
                        try:
                            validate_reservoir_cp_plan(p, plan)
                        except ValueError:
                            continue
                        yield plan


@pytest.mark.parametrize("release", [0, 1.5, 2.5, 4])
def test_arrival_identity_and_refinement_for_enumerated_plans(release):
    p = small(release=release)
    coarse = ArrivalIntervalPartition.build(p, 2 * T)
    evaluator = ArrivalCurveEvaluator()
    count = 0
    for plan in enumerate_plans(p):
        a = evaluator.evaluate(p, plan, coarse)
        times = {
            t
            for events in arrivals(p, plan).values()
            for t, n in events
            if 0 < t < coarse.points[-1]
        }
        fine = coarse.refine(times)
        b = evaluator.evaluate(p, plan, fine)
        assert (
            a["interval_tick_cost"] <= b["interval_tick_cost"] == a["exact_tick_cost"]
        )
        count += 1
    assert count > 10


@pytest.mark.parametrize("coefficients", [(0, 0), (0, 1), (1, 1), (1, 0)])
def test_resource_energy_minimum_against_full_tick_enumeration(coefficients):
    from ropeway_skip_stop_optimization.optimization.ddd.models import (
        DddResourceUsage,
        DddResource,
    )

    region = TimeRegion(0, 5, 1, 8, 0, 4)
    arc = BoundArc(0, 0, 0, 0, "x", region.vertices())
    u = DddResourceUsage(
        "r",
        0.000006,
        0.000001,
        leader_clear_wait_coefficient=coefficients[1],
        follower_enter_wait_coefficient=coefficients[0],
    )
    r = DddResource("r", 0.000002)
    for left in range(0, 10):
        for right in range(left + 1, 15):
            actual = []
            for t in range(0, 6):
                for v in range(1, 9):
                    if 0 <= v - t <= 4:
                        e = (v if coefficients[0] else t) + 1
                        c = (v if coefficients[1] else t) + 8
                        actual.append(max(0, min(c, right) - max(e, left)))
            assert minimum_overlap(arc, u, r, left, right) == min(actual)


@pytest.mark.parametrize("waiting", [False, True])
@pytest.mark.parametrize("journey_encoding", ["legacy", "ride_bounds", "time_moments"])
def test_lp_bounds_and_projections_for_every_small_plan(waiting, journey_encoding):
    p = small(waiting)
    plans = list(enumerate_plans(p))
    optimum = min(
        validate_reservoir_cp_plan(p, s).journey_time_tick / 1e6 for s in plans
    )
    native = DddReservoirCpSatOptimizer(
        DddIntegratedCpSatConfig(total_time_limit_seconds=5, num_workers=1)
    ).solve(p)
    assert native["proven_optimal"] and native["validated_upper_bound"] == optimum
    prepared = prepare_bound(p, ArrivalIntervalPartition.build(p, 2 * T))
    lbs = []
    for profile in ("arrival_only", "movement_capacity", "resource_windows"):
        b = ReservoirArrivalBoundBuilder().build(
            prepared, profile, journey_encoding=journey_encoding
        )
        try:
            for plan in plans:
                b.project(plan)
            bound, result = ReservoirArrivalBoundOptimizer().solve(
                b, deadline=perf_counter() + 10, threads=1
            )
            assert bound.value <= optimum + 1e-6
            lbs.append(bound.value)
        finally:
            b.model.dispose()
    assert lbs == sorted(lbs)


def test_scope_deadline_and_size_guards():
    p = small()
    with pytest.raises(ValueError, match="S6"):
        ReservoirOperatingDomain(p, "reusable")
    ledger = ReservoirCertificateLedger(p)
    ledger.accept_plan(DddReservoirCpPlan((), {}))
    with pytest.raises(ValueError, match="local/pool"):
        ledger.accept_bound(LocalRepairResult(2))
    with pytest.raises(ValueError, match="incompatible"):
        ledger.accept_bound(GlobalReservoirBound("foreign", 2, "m", "test"))
    with pytest.raises(ValueError, match="exceeds"):
        ledger.accept_bound(GlobalReservoirBound(p.fingerprint, 10, "m", "test"))
    with pytest.raises(TimeoutError):
        prepare_bound(p, ArrivalIntervalPartition.build(p, T), perf_counter() - 1)
    prepared = prepare_bound(p, ArrivalIntervalPartition.build(p, T))
    with pytest.raises(BoundSizeLimit):
        ReservoirArrivalBoundBuilder().build(prepared, max_variables=1)
    huge = replace(p, demand_groups=(replace(p.demand_groups[0], count=2**53),))
    with pytest.raises(ValueError, match="integer input range"):
        ReservoirArrivalBoundBuilder().build(
            prepare_bound(huge, ArrivalIntervalPartition.build(huge, T))
        )


def test_horizon_boundary_cost_is_not_credited_one_interval_early():
    p = small()
    tr = DddReservoirCpTrip(0, ("A_stop", "B_stop"), (2 * T, 4 * T), (0, 0), 6 * T)
    r = next(r for r in p.passenger_build.ride_candidates if r.board_visit_index == 0)
    plan = DddReservoirCpPlan((tr,), {r.id: 1})
    result = ArrivalCurveEvaluator().evaluate(
        p, plan, ArrivalIntervalPartition.build(p, 2 * T)
    )
    assert result["exact_tick_cost"] == result["interval_tick_cost"] == 4 * T
    bad = replace(tr, switch_ticks=(2 * T + 1, 4 * T + 1), return_tick=6 * T + 1)
    with pytest.raises(ValueError):
        validate_reservoir_cp_plan(p, DddReservoirCpPlan((bad,), {r.id: 1}))


def test_two_cabins_shared_capacity_and_same_visit_turnover():
    p = small(False)
    p = replace(
        p,
        available_fleet_count=2,
        movement_core=replace(
            p.movement_core, passenger_service_end_seconds=8, operational_end_seconds=10
        ),
        demand_groups=(
            EanDemandGroup("ab", "A", "B", 0, 2),
            EanDemandGroup("ba", "B", "A", 0, 2),
        ),
    )
    trips = tuple(
        DddReservoirCpTrip(
            k,
            ("A_stop", "B_stop", "A_stop", "B_stop"),
            tuple((2 * i + k) * T for i in range(4)),
            (0,) * 4,
            (8 + k) * T,
        )
        for k in range(2)
    )
    rides = {
        r.id: 1
        for r in p.passenger_build.ride_candidates
        if (r.demand_group_id == "ab" and r.board_visit_index == 0)
        or (r.demand_group_id == "ba" and r.board_visit_index == 1)
    }
    plan = DddReservoirCpPlan(trips, rides)
    assert validate_reservoir_cp_plan(p, plan).journey_time_tick == 14 * T
    prepared = prepare_bound(p, ArrivalIntervalPartition.build(p, 2 * T))
    b = ReservoirArrivalBoundBuilder().build(prepared)
    try:
        b.project(plan)
        bound, _ = ReservoirArrivalBoundOptimizer().solve(
            b, deadline=perf_counter() + 10, threads=1
        )
        cp = DddReservoirCpSatOptimizer(
            DddIntegratedCpSatConfig(total_time_limit_seconds=10, num_workers=1)
        ).solve(p)
        assert (
            cp["proven_optimal"] and bound.value <= cp["validated_upper_bound"] + 1e-6
        )
    finally:
        b.model.dispose()


def test_checkpoint_adapter_preserves_original_fingerprint(tmp_path):
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
        write_reservoir_cp_checkpoint,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
        load_reference,
    )

    p = small()
    plan = next(s for s in enumerate_plans(p) if s.ride_counts)
    path = tmp_path / "reference.json"
    write_reservoir_cp_checkpoint(path, p, plan)
    d, s = load_reference(path)
    assert d.fingerprint == p.fingerprint and s == plan


def test_positive_waiting_phase_is_not_restricted_onto_zero_wait():
    p = small()
    p = replace(
        p, waiting_policy=replace(p.waiting_policy, earliest_wait_time_seconds=3)
    )
    prepared = prepare_bound(p, ArrivalIntervalPartition.build(p, 2 * T))
    b = ReservoirArrivalBoundBuilder().build(prepared)
    try:
        for plan in enumerate_plans(p):
            b.project(plan)
    finally:
        b.model.dispose()


def test_optional_fleet_k1_k2_k4_and_lp_against_cp():
    previous = float("inf")
    for fleet in (1, 2, 4):
        p = replace(
            small(),
            available_fleet_count=fleet,
            demand_groups=(EanDemandGroup("g", "A", "B", 0, 3),),
        )
        cp = DddReservoirCpSatOptimizer(
            DddIntegratedCpSatConfig(total_time_limit_seconds=10, num_workers=1)
        ).solve(p)
        assert cp["proven_optimal"]
        assert cp["validated_upper_bound"] <= previous
        previous = cp["validated_upper_bound"]
        prepared = prepare_bound(p, ArrivalIntervalPartition.build(p, T))
        b = ReservoirArrivalBoundBuilder().build(prepared)
        try:
            lb, _ = ReservoirArrivalBoundOptimizer().solve(
                b, deadline=perf_counter() + 10, threads=1
            )
            assert lb.value <= previous + 1e-6
        finally:
            b.model.dispose()
