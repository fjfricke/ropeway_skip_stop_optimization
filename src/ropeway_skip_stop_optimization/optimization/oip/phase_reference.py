"""Exact regular OIP All-Stop reference on the shared integer movement grid.

One common phase spans a complete cycle. Integer-balanced offsets are retained;
no one-spacing symmetry assumption is made when the cycle is indivisible by K.
Passenger availability is constant between release/deadline thresholds. The
monotone phase-cell encoding follows ddd.all_stop_phase_cells, but trajectories
exist at t=0 and continue through the operational end: no reservoir or return.
"""
from bisect import bisect_right
from math import ceil, isfinite
from collections import defaultdict
from dataclasses import dataclass, replace
from time import monotonic

import gurobipy as gp
from gurobipy import GRB

from ..ean.builders.passenger_builder import expand_demands_to_ean_groups
from ..ean.fleet import EanFleetPlan
from ..ean.formulation_config import EanHorizonFormulation
from ..ean.models import EanFleetMode
from ..ean.optimizers.all_stop_mip_start import (
    _project_phase_to_boundary, _build_projected_route_visits, _visits_by_cabin_id,
)
from ..ean.passenger_plan import EanPassengerServicePlan, EanServedRideGroup
from ..ean.plan import EanMovementPlan, EanRouteDecision
from .validation import validate_oip_certificate, validate_oip_movement_certificate


@dataclass(frozen=True)
class PhaseRide:
    group_id: str
    cabin: int
    board_index: int
    alight_index: int
    board_tick: int
    alight_tick: int
    first: int
    last: int
    capacity: int


def regular_geometry(domain):
    if domain.fixed_k is None or domain.fixed_k <= 0:
        raise ValueError("regular OIP reference needs positive exact K")
    if any((s.max_wait_seconds or 0) != 0 for s in domain.artifact.config.station_configs):
        raise ValueError("regular OIP reference requires No-Wait")
    timings = {t.switch_id: t for t in domain.artifact.timings}
    ordered = tuple(timings[s] for s in domain.artifact.circulation_state_ids)
    grid = domain.grid
    service = tuple(grid.lower_tick(t.entry_to_platform_entry_seconds)
                    + grid.lower_tick(t.min_platform_entry_to_platform_exit_seconds)
                    + grid.lower_tick(t.platform_exit_to_exit_switch_seconds) for t in ordered)
    durations = tuple(s + grid.lower_tick(t.rope_to_next_switch_seconds)
                      for s, t in zip(service, ordered))
    boundaries = [0]
    for duration in durations:
        boundaries.append(boundaries[-1] + duration)
    cycle = boundaries[-1]
    offsets = tuple(k * cycle // domain.fixed_k for k in range(domain.fixed_k))
    return ordered, service, tuple(boundaries), offsets


def regular_movement(domain, phase_tick):
    ordered, service, boundaries, offsets = regular_geometry(domain)
    if not 0 <= phase_tick < boundaries[-1]:
        raise ValueError("common phase outside full cycle")
    artifact, grid = domain.artifact, domain.grid
    timing = {t.switch_id: t for t in ordered}
    decisions = {t.switch_id: EanRouteDecision.STOP for t in ordered}
    visits = _visits_by_cabin_id(artifact)
    from ..ean.plan import EanCabinTrajectory
    states, trajectories = [], []
    for cabin, offset in enumerate(offsets):
        state, first, tick = _project_phase_to_boundary(
            artifact=artifact, cabin_id=cabin,
            phase_seconds=grid.seconds((offset + phase_tick) % boundaries[-1]),
            boundaries=tuple(grid.seconds(b) for b in boundaries),
            route_seconds={t.switch_id: grid.seconds(s) for t, s in zip(ordered, service)},
            decisions_by_switch_id=decisions, timing_by_switch_id=timing,
        )
        states.append(state)
        trajectories.append(EanCabinTrajectory(cabin, _build_projected_route_visits(
            artifact=artifact, visits=visits[cabin], first_visit_index=first,
            first_switch_time=tick, timing_by_switch_id=timing,
            decisions_by_switch_id=decisions,
        )))
    # Projection helpers use floats. Restore exact grid values before fixed
    # passenger evaluation, especially boarding at t=0 (not -epsilon).
    time_fields = ("switch_time_seconds", "platform_entry_time_seconds",
                   "platform_exit_time_seconds", "exit_switch_time_seconds",
                   "next_switch_time_seconds")
    trajectories = [replace(t, visits=tuple(replace(v, **{
        name: grid.seconds(round(getattr(v, name) * grid.ticks_per_second))
        for name in time_fields if getattr(v, name) is not None
    }) for v in t.visits)) for t in trajectories]
    movement = EanMovementPlan(
        scenario_id=artifact.scenario_id, horizon_seconds=artifact.config.horizon_seconds,
        model_end_seconds=artifact.config.operational_end_seconds,
        trajectories=tuple(trajectories),
        horizon_formulation=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
        fleet_mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
    )
    fleet = EanFleetPlan(mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
        available_fleet_count=domain.k_max, active_cabin_ids=tuple(range(domain.fixed_k)),
        inactive_cabin_ids=tuple(range(domain.fixed_k, domain.k_max)), initial_states=tuple(states))
    validate_oip_movement_certificate(domain, movement, fleet)
    return movement, fleet


def phase_rides(domain, *, deadline=None):
    ordered, _, boundaries, offsets = regular_geometry(domain)
    grid, cycle = domain.grid, boundaries[-1]
    horizon = grid.upper_tick(domain.artifact.config.horizon_seconds)
    groups = expand_demands_to_ean_groups(domain.scenario)
    n = len(ordered)
    result = []
    for group in groups:
        if deadline is not None and monotonic() >= deadline:
            raise TimeoutError("phase reference preparation deadline")
        if group.origin_station_id == group.destination_station_id:
            raise ValueError("reference requires distinct OD stations")
        release = grid.lower_tick(group.release_time_seconds)
        for origin, timing in enumerate(ordered):
            if timing.station_id != group.origin_station_id:
                continue
            # A physical station can occur twice in a bidirectional circulation.
            # Every boarding occurrence is needed; first subsequent alighting
            # dominates later visits to the same destination in served-only mode.
            hops = next(h for h in range(1, n + 1)
                        if ordered[(origin + h) % n].station_id == group.destination_station_id)
            destination = (origin + hops) % n
            for cabin, offset in enumerate(offsets):
                for lap in range((horizon + 2 * cycle) // cycle + 2):
                    board_index = lap * n + origin
                    alight_index = board_index + hops
                    board = (lap * cycle + boundaries[origin] - offset
                             + grid.lower_tick(timing.entry_to_platform_entry_seconds)
                             + grid.lower_tick(timing.min_platform_entry_to_platform_exit_seconds))
                    alight = ((alight_index // n) * cycle + boundaries[destination] - offset
                              + grid.lower_tick(ordered[destination].entry_to_platform_entry_seconds))
                    first, last = max(0, alight - horizon), min(cycle - 1, board - release)
                    if first <= last:
                        result.append(PhaseRide(group.id, cabin, board_index, alight_index,
                            board, alight, first, last, min(group.count, domain.artifact.config.cabin_capacity)))
    return tuple(result), groups, cycle


def solve_phase_reference(domain, *, seconds=300, workers=12, seed=0,
                          require_full_service=True, fixed_phase_tick=None):
    """Search every grid phase; only full-service feasibility is calibrated.

    At fixed phase, served maximization is also exposed for enumeration tests.
    Any positive certificate is independently checked before being returned.
    """
    started = monotonic()
    deadline = started + seconds
    if seconds <= 0:
        return {"status": "UNKNOWN", "phase_tick": None}, None
    try:
        rides, groups, cycle = phase_rides(domain, deadline=deadline)
    except TimeoutError:
        return {"status": "UNKNOWN", "phase_tick": None}, None
    boundaries = sorted({0, cycle, *(r.first for r in rides), *(r.last + 1 for r in rides)})
    cell_count = len(boundaries) - 1
    indices = {tick: i for i, tick in enumerate(boundaries)}
    with gp.Model("oip_regular_all_stop_phase_cells") as model:
        model.Params.OutputFlag = 0
        model.Params.Threads = workers
        model.Params.Seed = seed
        model.Params.MIPGap = 0
        model.Params.SoftMemLimit = 30
        after = {i: model.addVar(vtype=GRB.BINARY) for i in range(1, cell_count)}
        for i in range(1, cell_count - 1):
            model.addConstr(after[i] >= after[i + 1])
        if fixed_phase_tick is not None:
            if not 0 <= fixed_phase_tick < cycle:
                raise ValueError("fixed phase outside cycle")
            selected = bisect_right(boundaries, fixed_phase_tick) - 1
            for i, var in after.items():
                var.LB = var.UB = int(selected >= i)
        quantities = []
        by_group, by_leg = defaultdict(list), defaultdict(list)
        for index, ride in enumerate(rides):
            if index % 1024 == 0 and monotonic() >= deadline:
                return {"status": "UNKNOWN", "phase_tick": None}, None
            q = model.addVar(lb=0, ub=ride.capacity, vtype=GRB.INTEGER)
            quantities.append(q)
            by_group[ride.group_id].append(q)
            for leg in range(ride.board_index, ride.alight_index):
                by_leg[ride.cabin, leg].append(q)
            first, end = indices[ride.first], indices[ride.last + 1]
            if first:
                model.addConstr(q <= ride.capacity * after[first])
            if end < cell_count:
                model.addConstr(q <= ride.capacity * (1 - after[end]))
        for group in groups:
            expr = gp.quicksum(by_group[group.id])
            model.addConstr(expr == group.count if require_full_service else expr <= group.count)
        for values in by_leg.values():
            model.addConstr(gp.quicksum(values) <= domain.artifact.config.cabin_capacity)
        model.setObjective(0 if require_full_service else -gp.quicksum(quantities))
        model.update()
        build_seconds = monotonic() - started
        if monotonic() >= deadline:
            return {"status": "UNKNOWN", "phase_tick": None}, None
        model.Params.TimeLimit = max(.001, deadline - monotonic())
        model.optimize()
        status = "INFEASIBLE" if model.Status == GRB.INFEASIBLE else "FEASIBLE" if model.SolCount else "UNKNOWN"
        stats = dict(status=status, phase_tick=None, variables=model.NumVars,
            constraints=model.NumConstrs, phase_cells=cell_count, build_seconds=build_seconds,
            solve_seconds=model.Runtime, native_status=model.Status)
        if not require_full_service:
            bound = float(model.ObjBound)
            stats["served_upper_bound"] = ceil(-bound) if isfinite(bound) else None
        if not model.SolCount:
            return stats, None
        phase = fixed_phase_tick if fixed_phase_tick is not None else boundaries[sum(round(v.X) for v in after.values())]
        movement, fleet = regular_movement(domain, phase)
        visits = {(t.cabin_id, v.station_id, round(v.platform_exit_time_seconds * domain.grid.ticks_per_second)): v
                  for t in movement.trajectories for v in t.visits}
        by_id = {g.id: g for g in groups}
        counts = {g.id: g.count for g in groups}
        served = []
        for ride, q in zip(rides, quantities):
            count = round(q.X)
            if not count:
                continue
            group = by_id[ride.group_id]
            board = visits[ride.cabin, group.origin_station_id, ride.board_tick - phase]
            alight = next(v for v in movement.trajectories[ride.cabin].visits
                if v.station_id == group.destination_station_id
                and round(v.platform_entry_time_seconds * domain.grid.ticks_per_second) == ride.alight_tick - phase)
            served.append(EanServedRideGroup(group.id, ride.cabin, board.visit_index,
                alight.visit_index, count, board.platform_exit_time_seconds, alight.platform_entry_time_seconds))
            counts[group.id] -= count
        passengers = EanPassengerServicePlan(domain.artifact.scenario_id,
            domain.artifact.config.horizon_seconds, tuple(served), counts)
        metrics = validate_oip_certificate(domain, movement, fleet, passengers)
        stats.update(phase_tick=phase, served=metrics.served, unserved=metrics.unserved,
                     journey_time_seconds=metrics.journey_time_seconds,
                     total_seconds=monotonic() - started)
        return stats, (movement, fleet, passengers)
