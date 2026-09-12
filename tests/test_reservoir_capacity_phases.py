from dataclasses import replace
from itertools import product
from time import perf_counter

import pytest

from test_reservoir_hybrid import small, enumerate_plans
from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddResource,
    DddResourceUsage,
    DddRouteDecision,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.network import (
    build_network,
    prepare_geometry,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.model import (
    build_model,
    solve,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    validate_reservoir_cp_plan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    DddReservoirCpTrip,
)

from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.formulation import (
    ReservoirPhaseFormulationConfig as Config,
)

T = 1_000_000


def physical_small(waiting=True, release=0):
    p = small(waiting, release)
    options = []
    for o in p.movement_core.route_options:
        uses = o.resource_usages
        if o.decision is DddRouteDecision.STOP:
            uses += (
                DddResourceUsage(
                    resource_id=f"exit_{o.station_id}",
                    leader_clear_offset_seconds=0.5,
                    follower_enter_offset_seconds=0.5,
                    leader_clear_wait_coefficient=1,
                    follower_enter_wait_coefficient=0,
                ),
            )
        options.append(replace(o, resource_usages=uses))
    return replace(
        p,
        movement_core=replace(
            p.movement_core,
            route_options=tuple(options),
            resources=p.movement_core.resources
            + (DddResource("exit_A", 0.25), DddResource("exit_B", 0.25)),
        ),
    )


def full_calendar(p):
    entries = {
        s: range(0, p.resolved_core.operational_end_tick + 1, T) for s in p.cycle_states
    }
    exits = {
        s: range(T // 2, p.resolved_core.operational_end_tick + 1, T)
        for s in p.cycle_states
    }
    return build_network(p, exact_entry_times=entries, exact_exit_times=exits)


@pytest.mark.parametrize("release", [0, 1.5, 2.5, 4])
@pytest.mark.parametrize("waiting", [False, True])
def test_all_enumerated_plans_replay_and_native_capacity(waiting, release):
    p = physical_small(waiting, release)
    plans = list(enumerate_plans(p))
    optimum = min(validate_reservoir_cp_plan(p, s).unserved for s in plans)
    net = full_calendar(p)
    b = build_model(net)
    try:
        for plan in plans:
            b.reference_values(plan)
        plan, result = solve(b, deadline=perf_counter() + 10, threads=1)
        assert result["status"] == 2
        assert result["validated_upper_bound"] == optimum
        assert result["global_lower_bound"] is None
        assert result["native_events"]
    finally:
        b.model.dispose()


def test_waiting_needs_real_single_occupancy_resource():
    with pytest.raises(ValueError, match="single-occupancy"):
        prepare_geometry(small(True))


def test_cumulative_deadlines_equal_fifo_individual_deadlines():
    for arrivals in product(range(5), repeat=2):
        if arrivals[0] >= arrivals[1]:
            continue
        for departures in product(range(7), repeat=2):
            if not arrivals[0] <= departures[0] < arrivals[1] <= departures[1]:
                continue
            for W in range(4):
                direct = all(d - a <= W for a, d in zip(arrivals, departures))
                cumulative = all(
                    sum(d <= s + W for d in departures) >= sum(a <= s for a in arrivals)
                    for s in arrivals
                )
                assert direct == cumulative


def test_seed_calendar_and_phase_release_replay():
    p = physical_small(release=1.5)
    p = replace(
        p, waiting_policy=replace(p.waiting_policy, earliest_wait_time_seconds=1.5)
    )
    plans = list(enumerate_plans(p))
    seed = next(s for s in plans if s.ride_counts)
    n = build_network(p, [seed], dispatch_spacing_tick=T)
    b = build_model(n, reference=seed)
    try:
        b.reference_values(seed)
    finally:
        b.model.dispose()


def test_deadline_is_not_infeasibility():
    with pytest.raises(TimeoutError):
        build_network(physical_small(), deadline=perf_counter() - 1)


def test_many_short_holds_cannot_exceed_visit_wait_limit():
    p = physical_small()
    net = full_calendar(p)
    b = build_model(net)
    try:
        for kind, t in (
            ("arrive", 0),
            ("hold", T // 2),
            ("hold", 3 * T // 2),
            ("hold", 5 * T // 2),
            ("exit", 3 * T + T // 2),
        ):
            a = next(
                a
                for a in net.arcs
                if a.kind == kind and a.option_id == "A_stop" and a.source[2] == t
            )
            b.model.addConstr(b.x[a.id] == 1)
        b.model.optimize()
        assert b.model.Status == 3
    finally:
        b.model.dispose()


@pytest.mark.parametrize(
    "config",
    [
        Config(),
        Config(passenger_encoding="od_flow"),
        Config(
            passenger_encoding="od_queue",
            passenger_integrality="boarding",
            passenger_network="contracted",
            resource_encoding="maximal",
            conflict_cuts="local_cliques",
        ),
    ],
)
def test_actual_bypass_overtaking_replays_without_fixed_order(config):
    p = replace(physical_small(), available_fleet_count=2)
    opts = []
    for o in p.movement_core.route_options:
        if o.decision is DddRouteDecision.STOP:
            uses = tuple(
                u for u in o.resource_usages if u.resource_id.startswith("exit_")
            )
            uses += (
                DddResourceUsage(
                    f"merge_{o.station_id}",
                    1.0,
                    1.0,
                    leader_clear_wait_coefficient=1,
                    follower_enter_wait_coefficient=1,
                ),
            )
        else:
            uses = (DddResourceUsage(f"merge_{o.station_id}", 0.1, 0.1),)
        opts.append(replace(o, resource_usages=uses))
    p = replace(
        p,
        movement_core=replace(
            p.movement_core,
            route_options=tuple(opts),
            resources=p.movement_core.resources
            + (DddResource("merge_A", 0.1), DddResource("merge_B", 0.1)),
        ),
    )
    plan = DddReservoirCpPlan(
        (
            DddReservoirCpTrip(0, ("A_stop", "B_skip"), (0, 2 * T), (0, 0), 3 * T),
            DddReservoirCpTrip(
                1, ("A_skip", "B_skip"), (T // 2, 3 * T // 2), (0, 0), 5 * T // 2
            ),
        ),
        {},
    )
    validate_reservoir_cp_plan(p, plan)
    assert plan.trips[1].switch_ticks[0] > plan.trips[0].switch_ticks[0]
    assert plan.trips[1].switch_ticks[1] < plan.trips[0].switch_ticks[1]
    b = build_model(build_network(p, [plan]), reference=plan, formulation=config)
    try:
        b.reference_values(plan)
    finally:
        b.model.dispose()


@pytest.mark.parametrize(
    "config",
    [
        Config(),
        Config(passenger_encoding="od_flow"),
        Config(
            passenger_encoding="od_queue",
            passenger_integrality="boarding",
            passenger_network="contracted",
            resource_encoding="maximal",
            conflict_cuts="local_cliques",
        ),
    ],
)
def test_two_cabins_turnover_integer_loads_and_horizon_tail(config):
    from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup

    p = replace(
        physical_small(False),
        available_fleet_count=2,
        cabin_capacity=2,
        movement_core=replace(
            physical_small(False).movement_core,
            passenger_service_end_seconds=8,
            operational_end_seconds=10,
        ),
        demand_groups=(
            EanDemandGroup("ab", "A", "B", 0, 3),
            EanDemandGroup("ba", "B", "A", 0, 3),
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
    counts = {
        r.id: 2 if r.cabin_id == 0 else 1
        for r in p.passenger_build.ride_candidates
        if (r.demand_group_id == "ab" and r.board_visit_index == 0)
        or (r.demand_group_id == "ba" and r.board_visit_index == 1)
    }
    plan = DddReservoirCpPlan(trips, counts)
    assert validate_reservoir_cp_plan(p, plan).served == 6
    b = build_model(build_network(p, [plan]), reference=plan, formulation=config)
    try:
        b.reference_values(plan)
        best, result = solve(b, deadline=perf_counter() + 10, threads=1, reference=plan)
        assert result["validated_upper_bound"] == 0
    finally:
        b.model.dispose()


@pytest.mark.parametrize(
    "config",
    [
        Config(),
        Config(passenger_encoding="od_flow"),
        Config(
            passenger_encoding="od_queue",
            passenger_integrality="boarding",
            passenger_network="contracted",
            resource_encoding="maximal",
            conflict_cuts="local_cliques",
        ),
    ],
)
def test_times_above_32bit_replay_without_rounding(config):
    p = physical_small()
    seed = next(s for s in enumerate_plans(p) if s.ride_counts)
    shift = 3000
    p = replace(
        p,
        dispatch_start_seconds=shift,
        dispatch_end_seconds=shift + 2,
        return_start_seconds=shift,
        movement_core=replace(
            p.movement_core,
            passenger_service_end_seconds=shift + 4,
            operational_end_seconds=shift + 6,
        ),
        demand_groups=tuple(
            replace(g, release_time_seconds=g.release_time_seconds + shift)
            for g in p.demand_groups
        ),
    )
    seed = replace(
        seed,
        trips=tuple(
            replace(
                tr,
                switch_ticks=tuple(t + shift * T for t in tr.switch_ticks),
                return_tick=tr.return_tick + shift * T,
            )
            for tr in seed.trips
        ),
    )
    b = build_model(build_network(p, [seed]), reference=seed, formulation=config)
    try:
        b.reference_values(seed)
    finally:
        b.model.dispose()
