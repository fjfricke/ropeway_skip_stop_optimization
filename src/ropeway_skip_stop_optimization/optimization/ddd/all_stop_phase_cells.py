"""Exact common-phase All-Stop feasibility through discrete support cells.

The regular movement is fixed up to one common integer phase.  Passenger ride
availability changes only at release, horizon, and early-return thresholds.
This module represents those exact cells with a monotone binary prefix instead
of attaching one activation Boolean to every passenger ride.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import asdict, dataclass
from time import perf_counter

import gurobipy as gp
from gurobipy import GRB

from .all_stop_phase import PreparedAllStopPhase
from .models import DddRouteDecision
from .reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    DddReservoirCpTrip,
    validate_reservoir_cp_plan,
)
from .time_ticks import ddd_seconds_to_tick


@dataclass(frozen=True, slots=True)
class AllStopPhaseCell:
    first_tick: int
    last_tick: int

    def __post_init__(self) -> None:
        if self.first_tick < 0 or self.last_tick < self.first_tick:
            raise ValueError("invalid All-Stop phase cell")


@dataclass(frozen=True, slots=True)
class PhaseCellRide:
    candidate_id: str
    demand_group_id: str
    cabin_id: int
    board_visit_index: int
    alight_visit_index: int
    first_cell: int
    last_cell: int
    upper_bound: int


@dataclass(frozen=True, slots=True)
class PreparedAllStopPhaseCells:
    phase: PreparedAllStopPhase
    cells: tuple[AllStopPhaseCell, ...]
    rides: tuple[PhaseCellRide, ...]


def prepare_all_stop_phase_cells(
    phase: PreparedAllStopPhase,
) -> PreparedAllStopPhaseCells:
    """Partition every integer phase tick by its exact passenger support."""
    problem = phase.problem
    maximum = phase.maximum_phase_tick
    groups = {group.id: group for group in problem.demand_groups}
    options = {option.id: option for option in problem.resolved_core.route_options}
    visits = {
        (trip.cabin_id, index): (options[option_id], tick)
        for trip in phase.trips
        for index, (option_id, tick) in enumerate(
            zip(trip.route_option_ids, trip.switch_ticks, strict=True)
        )
    }
    visits_per_cycle = len(problem.cycle_states)
    service_end = problem.resolved_core.passenger_service_end_tick
    trip_by_id = {trip.cabin_id: trip for trip in phase.trips}
    early_threshold = {
        trip.cabin_id: service_end - (trip.return_tick - phase.cycle_tick)
        for trip in phase.trips
    }
    boundaries = {0, maximum + 1}
    for threshold in early_threshold.values():
        if 0 < threshold <= maximum:
            boundaries.add(threshold)

    raw_rides = []
    for candidate in problem.passenger_build.ride_candidates:
        board = visits.get((candidate.cabin_id, candidate.board_visit_index))
        alight = visits.get((candidate.cabin_id, candidate.alight_visit_index))
        if board is None or alight is None:
            continue
        board_option, board_base = board
        alight_option, alight_base = alight
        if (
            board_option.decision is not DddRouteDecision.STOP
            or alight_option.decision is not DddRouteDecision.STOP
            or board_option.platform_exit_offset_seconds is None
            or alight_option.platform_entry_offset_seconds is None
        ):
            continue
        group = groups[candidate.demand_group_id]
        departure_base = board_base + ddd_seconds_to_tick(
            board_option.platform_exit_offset_seconds
        )
        arrival_base = alight_base + ddd_seconds_to_tick(
            alight_option.platform_entry_offset_seconds
        )
        first_tick = max(
            0,
            ddd_seconds_to_tick(group.release_time_seconds) - departure_base,
        )
        last_tick = min(maximum, service_end - arrival_base)
        trip = trip_by_id[candidate.cabin_id]
        last_lap_start = len(trip.route_option_ids) - visits_per_cycle
        if candidate.alight_visit_index >= last_lap_start:
            last_tick = min(last_tick, early_threshold[candidate.cabin_id] - 1)
        if first_tick > last_tick:
            continue
        if first_tick:
            boundaries.add(first_tick)
        if last_tick < maximum:
            boundaries.add(last_tick + 1)
        raw_rides.append((candidate, first_tick, last_tick, group.count))

    ordered = tuple(sorted(boundaries))
    cells = tuple(
        AllStopPhaseCell(left, right - 1)
        for left, right in zip(ordered, ordered[1:])
    )
    boundary_index = {tick: index for index, tick in enumerate(ordered)}
    rides = tuple(
        PhaseCellRide(
            candidate.id,
            candidate.demand_group_id,
            candidate.cabin_id,
            candidate.board_visit_index,
            candidate.alight_visit_index,
            boundary_index[first_tick],
            boundary_index[last_tick + 1] - 1,
            min(problem.cabin_capacity, count),
        )
        for candidate, first_tick, last_tick, count in raw_rides
    )
    return PreparedAllStopPhaseCells(phase, cells, rides)


def phase_cell_index(prepared: PreparedAllStopPhaseCells, tick: int) -> int:
    if not 0 <= tick <= prepared.phase.maximum_phase_tick:
        raise ValueError("phase tick lies outside the prepared domain")
    starts = tuple(cell.first_tick for cell in prepared.cells)
    return bisect_right(starts, tick) - 1


def movement_at_phase(
    prepared: PreparedAllStopPhaseCells,
    phase_tick: int,
    ride_counts: dict[str, int] | None = None,
) -> DddReservoirCpPlan:
    """Materialize the deterministic regular movement at an exact phase."""
    phase_cell_index(prepared, phase_tick)
    base = prepared.phase
    service_end = base.problem.resolved_core.passenger_service_end_tick
    visits_per_cycle = len(base.problem.cycle_states)
    trips = []
    for trip in base.trips:
        early = phase_tick + trip.return_tick - base.cycle_tick >= service_end
        keep = len(trip.route_option_ids) - visits_per_cycle if early else len(
            trip.route_option_ids
        )
        trips.append(
            DddReservoirCpTrip(
                trip.cabin_id,
                trip.route_option_ids[:keep],
                tuple(tick + phase_tick for tick in trip.switch_ticks[:keep]),
                trip.wait_ticks[:keep],
                trip.return_tick
                + phase_tick
                - (base.cycle_tick if early else 0),
            )
        )
    return DddReservoirCpPlan(tuple(trips), ride_counts or {})


def solve_all_stop_phase_cells(
    prepared: PreparedAllStopPhaseCells,
    *,
    time_limit_seconds: float,
    workers: int,
    seed: int = 0,
    phase_hint_tick: int | None = None,
    log_search_progress: bool = False,
    build_only: bool = False,
    deadline: float | None = None,
) -> tuple[dict, DddReservoirCpPlan | None]:
    """Solve exact full-service feasibility over all common-phase cells."""
    started = perf_counter()
    if time_limit_seconds <= 0 or workers <= 0:
        raise ValueError("time limit and workers must be positive")
    problem = prepared.phase.problem
    groups = {group.id: group for group in problem.demand_groups}
    model = gp.Model("all_stop_phase_cell_passengers")
    model.Params.OutputFlag = int(log_search_progress)
    model.Params.Threads = workers
    model.Params.Seed = seed
    model.Params.MIPGap = 0

    # after[j] is one iff the selected cell index is at least j.  Fixed
    # endpoints and monotonicity encode exactly one transition/cell.
    cell_count = len(prepared.cells)
    after = {
        j: model.addVar(vtype=GRB.BINARY, name=f"phase_after[{j}]")
        for j in range(1, cell_count)
    }
    for j in range(1, cell_count - 1):
        model.addConstr(after[j] >= after[j + 1], name=f"phase_monotone[{j}]")

    quantities = {}
    by_group = defaultdict(list)
    by_leg = defaultdict(list)
    for ride in prepared.rides:
        q = model.addVar(
            lb=0,
            ub=ride.upper_bound,
            vtype=GRB.INTEGER,
            name=ride.candidate_id,
        )
        quantities[ride.candidate_id] = q
        by_group[ride.demand_group_id].append(q)
        for leg in range(ride.board_visit_index, ride.alight_visit_index):
            by_leg[ride.cabin_id, leg].append(q)
        if ride.first_cell > 0:
            model.addConstr(
                q <= ride.upper_bound * after[ride.first_cell],
                name=f"phase_lower[{ride.candidate_id}]",
            )
        if ride.last_cell + 1 < cell_count:
            model.addConstr(
                q <= ride.upper_bound * (1 - after[ride.last_cell + 1]),
                name=f"phase_upper[{ride.candidate_id}]",
            )

    for group_id, group in groups.items():
        model.addConstr(
            gp.quicksum(by_group[group_id]) == group.count,
            name=f"demand[{group_id}]",
        )
    for (cabin_id, leg), values in by_leg.items():
        model.addConstr(
            gp.quicksum(values) <= problem.cabin_capacity,
            name=f"capacity[{cabin_id},{leg}]",
        )
    model.setObjective(0.0, GRB.MINIMIZE)
    model.update()

    if phase_hint_tick is not None:
        hint_cell = phase_cell_index(prepared, phase_hint_tick)
        for j, variable in after.items():
            variable.Start = int(hint_cell >= j)

    stats = {
        "variables": model.NumVars,
        "binary_phase_variables": len(after),
        "ride_variables": len(quantities),
        "constraints": model.NumConstrs,
        "phase_cells": cell_count,
    }
    build_seconds = perf_counter() - started
    if build_only:
        model.dispose()
        return (
            {
                "schema": "all_stop_phase_cell_result_v1",
                "solver_status": "NOT_RUN",
                "proven_optimal": False,
                "proven_feasible": False,
                "proven_infeasible": False,
                "proof_scope": "REGULAR_NO_WAIT_ALL_STOP_COMMON_PHASE_CELLS",
                "phase_tick": None,
                "phase_cell": None,
                "metrics": None,
                "model_stats": stats,
                "build_seconds": build_seconds,
                "solve_seconds": 0.0,
                "total_seconds": perf_counter() - started,
            },
            None,
        )

    remaining = time_limit_seconds - build_seconds
    if deadline is not None:
        remaining = min(remaining, deadline - perf_counter())
    if remaining > 0:
        model.Params.TimeLimit = max(0.001, remaining)
        before = perf_counter()
        model.optimize()
        solve_seconds = perf_counter() - before
    else:
        solve_seconds = 0.0
    status = model.Status if remaining > 0 else GRB.TIME_LIMIT
    status_name = {
        GRB.OPTIMAL: "OPTIMAL",
        GRB.INFEASIBLE: "INFEASIBLE",
        GRB.TIME_LIMIT: "TIME_LIMIT",
        GRB.INTERRUPTED: "INTERRUPTED",
        GRB.MEM_LIMIT: "MEM_LIMIT",
        GRB.INF_OR_UNBD: "INF_OR_UNBD",
    }.get(status, str(status))
    plan = None
    metrics = None
    selected_cell = None
    selected_phase = None
    if model.SolCount:
        selected_cell = sum(int(variable.X >= 0.5) for variable in after.values())
        selected_phase = prepared.cells[selected_cell].first_tick
        counts = {
            candidate_id: int(round(variable.X))
            for candidate_id, variable in quantities.items()
            if variable.X >= 0.5
        }
        plan = movement_at_phase(prepared, selected_phase, counts)
        metrics = validate_reservoir_cp_plan(problem, plan)
        if metrics.unserved:
            model.dispose()
            raise RuntimeError("phase-cell full-service model exported an incomplete plan")
    result = {
        "schema": "all_stop_phase_cell_result_v1",
        "solver_status": status_name,
        "proven_optimal": status in (GRB.OPTIMAL, GRB.INFEASIBLE),
        "proven_feasible": plan is not None,
        "proven_infeasible": status == GRB.INFEASIBLE,
        "proof_scope": "REGULAR_NO_WAIT_ALL_STOP_COMMON_PHASE_CELLS",
        "phase_tick": selected_phase,
        "phase_cell": selected_cell,
        "metrics": None if metrics is None else asdict(metrics),
        "model_stats": stats,
        "build_seconds": build_seconds,
        "solve_seconds": solve_seconds,
        "node_count": None if remaining <= 0 else model.NodeCount,
        "solution_count": None if remaining <= 0 else model.SolCount,
        "total_seconds": perf_counter() - started,
    }
    model.dispose()
    return result, plan
