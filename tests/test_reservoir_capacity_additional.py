"""Additional independent assignment regressions; no performance runs."""

import pytest
from itertools import product
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.formulation import (
    ReservoirPhaseFormulationConfig as Config,
)
from time import perf_counter

from test_optimization_ean_passenger_service import _odd_cycle_fixed_movement_case
from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddMovementCore,
    DddMovementState,
    DddResource,
    DddResourceUsage,
    DddRouteOption,
    DddRouteDecision,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_problem import (
    DddReservoirCpSatProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    DddReservoirCpTrip,
    validate_reservoir_cp_plan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.network import (
    build_network,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.model import (
    build_model,
    solve,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup


@pytest.mark.parametrize("encoding", ("legacy", "od_flow", "od_queue"))
@pytest.mark.parametrize("integrality", ("all", "boarding"))
def test_original_odd_cycle_embedded_with_skip_only_reservoir_tails(
    encoding, integrality
):
    scenario, artifact, original = _odd_cycle_fixed_movement_case()
    states = artifact.state_ids
    options = tuple(
        DddRouteOption(
            id=f"{s}:{decision.value}",
            from_state_id=s,
            to_state_id=states[(i + 1) % 3],
            station_id=str(i),
            decision=decision,
            duration_seconds=1,
            platform_entry_offset_seconds=0.2
            if decision is DddRouteDecision.STOP
            else None,
            platform_exit_offset_seconds=0.5
            if decision is DddRouteDecision.STOP
            else None,
            exit_switch_offset_seconds=0.7,
            resource_usages=(DddResourceUsage(s, 0.0, 0.0),),
        )
        for i, s in enumerate(states)
        for decision in DddRouteDecision
    )
    p = DddReservoirCpSatProblem(
        DddMovementCore(
            "odd_cycle_reservoir_embedding",
            6,
            9,
            tuple(DddMovementState(s) for s in states),
            options,
            tuple(DddResource(s, 0.1) for s in states),
        ),
        tuple(
            EanDemandGroup(
                f"g{i}", d.origin, d.destination, float(d.arrival_time.second + 1), 1
            )
            for i, d in enumerate(scenario.demands)
        ),
        1,
        2,
        states[0],
        1,
    )
    trips = []
    for tr in original.trajectories:
        ids = [f"{v.switch_id}:{v.decision.value}" for v in tr.visits]
        times = [int((v.switch_time_seconds + 1) * 1e6) for v in tr.visits]
        if tr.cabin_id == 1:
            ids = [f"{states[0]}:skip", *ids, f"{states[1]}:skip", f"{states[2]}:skip"]
            times = [0, *times, 7_000_000, 8_000_000]
        trips.append(
            DddReservoirCpTrip(
                tr.cabin_id,
                tuple(ids),
                tuple(times),
                (0,) * len(ids),
                7_000_000 if tr.cabin_id == 0 else 9_000_000,
            )
        )
    seed = DddReservoirCpPlan(tuple(trips), {})
    validate_reservoir_cp_plan(p, seed)
    choices = []
    for g in p.demand_groups:
        candidates = [None]
        for r in p.passenger_build.ride_candidates:
            if r.demand_group_id != g.id:
                continue
            try:
                validate_reservoir_cp_plan(p, DddReservoirCpPlan(seed.trips, {r.id: 1}))
            except ValueError:
                continue
            candidates.append(r.id)
        choices.append(candidates)
    optimum = len(p.demand_groups)
    for selected in product(*choices):
        plan = DddReservoirCpPlan(seed.trips, {r: 1 for r in selected if r is not None})
        try:
            metrics = validate_reservoir_cp_plan(p, plan)
        except ValueError:
            continue
        optimum = min(optimum, metrics.unserved)
    b = build_model(
        build_network(p, [seed]),
        reference=seed,
        formulation=Config(
            passenger_encoding=encoding,
            passenger_integrality=integrality,
            passenger_network="contracted",
        ),
    )
    try:
        values = b.reference_values(seed)
        for v in b.x.values():
            b.model.addConstr(v == values[v.index])
        if integrality == "all":
            assert all(v.VType == "I" for v in b.flow.values())
        _, r = solve(b, deadline=perf_counter() + 10, threads=1, reference=seed)
        assert r["validated_upper_bound"] == optimum
        lp = b.model.relax()
        lp.Params.OutputFlag = 0
        try:
            lp.optimize()
            assert lp.ObjVal <= optimum + 1e-6
        finally:
            lp.dispose()
    finally:
        b.model.dispose()
