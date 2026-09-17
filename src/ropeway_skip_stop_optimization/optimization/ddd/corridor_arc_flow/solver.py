from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import StrEnum
import math
from time import perf_counter

import gurobipy as gp
from gurobipy import GRB

from .domain import (
    CorridorArc,
    CorridorArcFlowMode,
    CorridorPreparedProblem,
    CorridorResourceWindow,
)
from ..models import DddRouteDecision
from ..fixed_k_certificate import DddFixedKPrimalValidator
from ..reference import (
    DddReferenceSolution,
    DddReferenceTrajectory,
    build_ddd_reference_visit,
    validate_ddd_reference_solution,
)
from ..route_topology import unique_stop_route_option
from ..time_ticks import ddd_seconds_to_tick, ddd_tick_to_seconds


class CorridorArcFlowStatus(StrEnum):
    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    UNKNOWN = "unknown"
    RELAXED_FEASIBLE = "relaxed_feasible"
    VALIDATION_ERROR = "validation_error"


@dataclass(frozen=True, slots=True)
class CorridorArcFlowSolveConfig:
    mode: CorridorArcFlowMode = CorridorArcFlowMode.INNER
    time_limit_seconds: float = 300.0
    threads: int | None = None
    seed: int = 0
    mip_gap: float = 0.0
    output_flag: bool = False
    memory_limit_gib: float | None = None

    def validate(self) -> None:
        if not isinstance(self.mode, CorridorArcFlowMode):
            raise ValueError("invalid corridor mode")
        if not math.isfinite(self.time_limit_seconds) or self.time_limit_seconds <= 0:
            raise ValueError("corridor time limit must be positive")
        if self.threads is not None and self.threads <= 0:
            raise ValueError("corridor threads must be positive")
        if self.seed < 0 or not 0 <= self.mip_gap <= 1:
            raise ValueError("invalid corridor solver controls")
        if self.memory_limit_gib is not None and self.memory_limit_gib <= 0:
            raise ValueError("corridor memory limit must be positive")


@dataclass(frozen=True, slots=True)
class CorridorArcFlowProgress:
    kind: str
    elapsed_seconds: float
    objective_value: float | None
    solver_bound: float | None
    node_count: float


@dataclass(frozen=True, slots=True)
class CorridorPassengerSeedResult:
    ride_counts: tuple[tuple[str, int], ...]
    unserved: int
    optimal: bool
    solve_seconds: float


@dataclass(frozen=True, slots=True)
class CorridorArcFlowResult:
    status: CorridorArcFlowStatus
    mode: CorridorArcFlowMode
    problem_fingerprint: str
    model_fingerprint: str
    objective_value: int | None
    solver_bound: float | None
    certified_global_lower_bound: int | None
    solution: DddReferenceSolution | None
    relaxed_candidate: DddReferenceSolution | None
    ride_counts: tuple[tuple[str, int], ...]
    selected_corridor_ids: tuple[str, ...]
    variable_count: int
    constraint_count: int
    corridor_count: int
    resource_conflict_count: int
    build_seconds: float
    solve_seconds: float
    total_seconds: float
    node_count: float
    progress: tuple[CorridorArcFlowProgress, ...]
    detail: str | None = None


@dataclass(slots=True)
class _Built:
    model: gp.Model
    time: dict[tuple[int, int], gp.Var]
    wait: dict[tuple[int, int], gp.Var]
    active: dict[tuple[int, int], gp.Var]
    route: dict[tuple[int, int, str], gp.Var]
    corridor: dict[str, gp.Var]
    ride: dict[str, gp.Var]
    unserved: dict[str, gp.Var]
    constraint_count: int
    resource_conflict_count: int


def _resource_conflicts(prepared, mode):
    grouped = defaultdict(list)
    for arc in prepared.arcs:
        for window in arc.resources:
            interval = window.outer if mode is CorridorArcFlowMode.INNER else window.mandatory_core
            if interval is not None:
                grouped[window.resource_id].append((interval, arc.id))
    rows = set()
    forbidden = set()
    boundary_by_resource = defaultdict(list)
    # Fixed pre-horizon occupancies are part of both proof domains.
    movement = prepared.problem.resolved_trajectory_problem.structural_movement_problem
    resources = movement.resources_by_id
    for occurrence in prepared.problem.boundary_context.resource_occurrences:
        resource = resources[occurrence.resource_id]
        lower = max(0, ddd_seconds_to_tick(occurrence.follower_enter_time_seconds))
        upper = ddd_seconds_to_tick(occurrence.leader_clear_time_seconds) + occurrence.separation_after_tick(resource)
        if lower >= upper:
            continue
        boundary_by_resource[occurrence.resource_id].append((lower, upper))
    for resource_id, entries in grouped.items():
        events = defaultdict(lambda: {"add": [], "remove": [], "fixed_add": 0, "fixed_remove": 0})
        for interval, arc_id in entries:
            events[interval.lower_tick]["add"].append(arc_id)
            events[interval.upper_tick]["remove"].append(arc_id)
        for lower, upper in boundary_by_resource.get(resource_id, ()):
            events[lower]["fixed_add"] += 1
            events[upper]["fixed_remove"] += 1
        active = Counter()
        fixed = 0
        for tick in sorted(events):
            event = events[tick]
            for arc_id in event["remove"]:
                active[arc_id] -= 1
                if active[arc_id] == 0:
                    del active[arc_id]
            fixed -= event["fixed_remove"]
            for arc_id in event["add"]:
                active[arc_id] += 1
            fixed += event["fixed_add"]
            if fixed > 1:
                raise ValueError("boundary resource occurrences already conflict")
            for arc_id, coefficient in active.items():
                if coefficient + fixed > 1:
                    forbidden.add(arc_id)
            coefficients = tuple(sorted(
                (arc_id, coefficient) for arc_id, coefficient in active.items()
                if arc_id not in forbidden
            ))
            rhs = 1 - fixed
            if coefficients and (len(coefficients) > 1 or coefficients[0][1] > rhs):
                rows.add((rhs, coefficients))
    return tuple(sorted(rows)), tuple(sorted(forbidden))


def _build(
    prepared: CorridorPreparedProblem,
    config: CorridorArcFlowSolveConfig,
    seed,
    seed_ride_counts: dict[str, int] | None,
):
    started = perf_counter()
    problem = prepared.problem
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    options = {option.id: option for option in movement.route_options}
    states_by_cabin = dict(prepared.states_by_cabin)
    options_by_visit = {(c, v): ids for c, v, ids in prepared.options_by_visit}
    arcs_by_key = defaultdict(list)
    for arc in prepared.arcs:
        arcs_by_key[arc.cabin_id, arc.visit_index, arc.option_id].append(arc)
    model = gp.Model("ddd_corridor_arc_flow")
    model.Params.OutputFlag = int(config.output_flag)
    model.Params.TimeLimit = config.time_limit_seconds
    model.Params.Seed = config.seed
    model.Params.MIPGap = config.mip_gap
    model.Params.NumericFocus = 3
    model.Params.FeasibilityTol = 1e-8
    model.Params.IntFeasTol = 1e-8
    if config.threads is not None:
        model.Params.Threads = config.threads
    if config.memory_limit_gib is not None:
        model.Params.MemLimit = config.memory_limit_gib
    max_completion = movement.operational_end_tick + max(
        option.duration_tick + ddd_seconds_to_tick(prepared.waiting_policy.maximum_wait_seconds(option.station_id))
        for option in movement.route_options
    )
    time, wait, active, route, corridor = {}, {}, {}, {}, {}
    constraints = 0
    start_by_cabin = {s.cabin_id: s for s in movement.starts}
    for cabin, states in prepared.states_by_cabin:
        start = start_by_cabin[cabin]
        count = start.max_visit_count
        for visit in range(count + 1):
            time[cabin, visit] = model.addVar(
                lb=start.time_tick if visit == 0 else 0,
                ub=start.time_tick if visit == 0 else max_completion,
                vtype=GRB.INTEGER, name=f"time[{cabin},{visit}]",
            )
            active[cabin, visit] = model.addVar(vtype=GRB.BINARY, name=f"active[{cabin},{visit}]")
        model.addConstr(active[cabin, 0] == 1)
        model.addConstr(active[cabin, count] == 0)
        constraints += 2
        for visit in range(count + 1):
            model.addGenConstrIndicator(active[cabin, visit], True, time[cabin, visit] <= movement.operational_end_tick)
            model.addGenConstrIndicator(active[cabin, visit], False, time[cabin, visit] >= movement.operational_end_tick + 1)
            constraints += 2
            if visit < count:
                model.addConstr(active[cabin, visit] >= active[cabin, visit + 1])
                constraints += 1
        for visit in range(count):
            option_ids = options_by_visit[cabin, visit]
            option_wait_caps = {
                option_id: (
                    ddd_seconds_to_tick(
                        prepared.waiting_policy.maximum_wait_seconds(options[option_id].station_id)
                    )
                    if options[option_id].decision is DddRouteDecision.STOP else 0
                )
                for option_id in option_ids
            }
            wait[cabin, visit] = model.addVar(
                lb=0,
                ub=max(option_wait_caps.values()),
                vtype=GRB.INTEGER,
                name=f"wait[{cabin},{visit}]",
            )
            route_vars = []
            for option_id in option_ids:
                variable = model.addVar(vtype=GRB.BINARY, name=f"route[{cabin},{visit},{option_id}]")
                route[cabin, visit, option_id] = variable
                route_vars.append(variable)
                arc_vars = []
                for arc in arcs_by_key[cabin, visit, option_id]:
                    z = model.addVar(vtype=GRB.BINARY, name=arc.id)
                    corridor[arc.id] = z
                    arc_vars.append(z)
                    model.addGenConstrIndicator(z, True, time[cabin, visit] >= arc.source_interval.lower_tick)
                    model.addGenConstrIndicator(z, True, time[cabin, visit] <= arc.source_interval.last_tick)
                    model.addGenConstrIndicator(z, True, wait[cabin, visit] >= arc.wait_interval.lower_tick)
                    model.addGenConstrIndicator(z, True, wait[cabin, visit] <= arc.wait_interval.last_tick)
                    constraints += 4
                model.addConstr(gp.quicksum(arc_vars) == variable)
                constraints += 1
            model.addConstr(gp.quicksum(route_vars) == active[cabin, visit])
            # Keep microsecond ticks exact without putting route durations as
            # large coefficients on binaries.  The direct linear selection
            # produced false root cutoffs on otherwise accepted MIP starts.
            for option_id in option_ids:
                model.addGenConstrIndicator(
                    route[cabin, visit, option_id],
                    True,
                    time[cabin, visit + 1]
                    == time[cabin, visit] + wait[cabin, visit] + options[option_id].duration_tick,
                )
                model.addGenConstrIndicator(
                    route[cabin, visit, option_id],
                    True,
                    wait[cabin, visit] <= option_wait_caps[option_id],
                )
            constraints += 1 + 2 * len(option_ids)
            positive = model.addVar(vtype=GRB.BINARY, name=f"wait_positive[{cabin},{visit}]")
            model.addConstr(wait[cabin, visit] >= positive)
            model.addGenConstrIndicator(positive, False, wait[cabin, visit] == 0)
            constraints += 2
            for option_id in option_ids:
                option = options[option_id]
                if option.decision is not DddRouteDecision.STOP or option.platform_exit_offset_seconds is None:
                    continue
                both = model.addVar(vtype=GRB.BINARY, name=f"wait_route[{cabin},{visit},{option_id}]")
                model.addGenConstrAnd(both, [positive, route[cabin, visit, option_id]])
                model.addGenConstrIndicator(
                    both, True,
                    time[cabin, visit] + ddd_seconds_to_tick(option.platform_exit_offset_seconds)
                    >= ddd_seconds_to_tick(prepared.waiting_policy.earliest_wait_time_seconds),
                )
                constraints += 2

    resource_rows, forbidden = _resource_conflicts(prepared, config.mode)
    for arc_id in forbidden:
        model.addConstr(corridor[arc_id] == 0, name=f"resource_forbid[{arc_id}]")
        constraints += 1
    for index, (rhs, coefficients) in enumerate(resource_rows):
        model.addConstr(
            gp.quicksum(coefficient * corridor[arc_id] for arc_id, coefficient in coefficients) <= rhs,
            name=f"resource_clique[{index}]",
        )
        constraints += 1

    groups = {group.id: group for group in problem.passenger_build.demand_groups}
    stop_by_state = {
        state: unique_stop_route_option(movement, state, error_context="corridor passengers")
        for _, states in prepared.states_by_cabin for state in states[:-1]
    }
    ride, used, unserved = {}, {}, {}
    by_group, onboard = defaultdict(list), defaultdict(list)
    capacity = problem.artifact.config.cabin_capacity
    service_end = movement.passenger_service_end_tick
    for index, candidate in enumerate(problem.passenger_build.ride_candidates):
        board = candidate.cabin_id, candidate.board_visit_index
        alight = candidate.cabin_id, candidate.alight_visit_index
        if board not in wait or alight not in wait:
            continue
        group = groups[candidate.demand_group_id]
        q = model.addVar(lb=0, ub=min(capacity, group.count), vtype=GRB.INTEGER, name=f"passengers[{index}]")
        y = model.addVar(vtype=GRB.BINARY, name=f"ride_used[{index}]")
        ride[candidate.id], used[candidate.id] = q, y
        model.addConstr(q <= min(capacity, group.count) * y)
        model.addConstr(q >= y)
        model.addConstr(y <= route[*board, stop_by_state[states_by_cabin[board[0]][board[1]]].id])
        model.addConstr(y <= route[*alight, stop_by_state[states_by_cabin[alight[0]][alight[1]]].id])
        stop_board = stop_by_state[states_by_cabin[board[0]][board[1]]]
        stop_alight = stop_by_state[states_by_cabin[alight[0]][alight[1]]]
        board_expr = time[board] + ddd_seconds_to_tick(stop_board.platform_exit_offset_seconds) + wait[board]
        alight_expr = time[alight] + ddd_seconds_to_tick(stop_alight.platform_entry_offset_seconds)
        model.addGenConstrIndicator(y, True, board_expr >= ddd_seconds_to_tick(group.release_time_seconds))
        model.addGenConstrIndicator(y, True, board_expr <= service_end)
        model.addGenConstrIndicator(y, True, alight_expr <= service_end)
        model.addGenConstrIndicator(y, True, alight_expr >= board_expr)
        constraints += 8
        by_group[group.id].append(q)
        for visit in range(candidate.board_visit_index, candidate.alight_visit_index):
            onboard[candidate.cabin_id, visit].append(q)
    for group in groups.values():
        variable = model.addVar(lb=0, ub=group.count, vtype=GRB.INTEGER, name=f"unserved[{group.id}]")
        unserved[group.id] = variable
        model.addConstr(gp.quicksum(by_group[group.id]) + variable == group.count)
        constraints += 1
    for key, values in onboard.items():
        model.addConstr(gp.quicksum(values) <= capacity * active[key])
        constraints += 1
    model.setObjective(gp.quicksum(unserved.values()), GRB.MINIMIZE)

    if seed is not None:
        seed_visits = {(t.cabin_id, v.visit_index): v for t in seed.trajectories for v in t.visits}
        for key, variable in time.items():
            visit = seed_visits.get(key)
            if visit is not None:
                variable.Start = ddd_seconds_to_tick(visit.switch_time_seconds)
        for key, variable in wait.items():
            visit = seed_visits.get(key)
            variable.Start = 0 if visit is None else ddd_seconds_to_tick(visit.wait_seconds)
        for key, variable in route.items():
            visit = seed_visits.get(key[:2])
            variable.Start = int(visit is not None and visit.route_option_id == key[2])
        for arc in prepared.arcs:
            visit = seed_visits.get((arc.cabin_id, arc.visit_index))
            corridor[arc.id].Start = int(
                visit is not None and visit.route_option_id == arc.option_id
                and arc.source_interval.contains_tick(ddd_seconds_to_tick(visit.switch_time_seconds))
                and arc.wait_interval.contains_tick(ddd_seconds_to_tick(visit.wait_seconds))
            )
        if seed_ride_counts is not None:
            validated_unserved = validate_corridor_passenger_assignment(
                prepared, seed, tuple(sorted(seed_ride_counts.items()))
            )
            del validated_unserved
            served_by_group = defaultdict(int)
            candidates = {item.id: item for item in problem.passenger_build.ride_candidates}
            for ride_id, variable in ride.items():
                value = seed_ride_counts.get(ride_id, 0)
                variable.Start = value
                used[ride_id].Start = int(value > 0)
                served_by_group[candidates[ride_id].demand_group_id] += value
            for group_id, variable in unserved.items():
                variable.Start = groups[group_id].count - served_by_group[group_id]
    model.update()
    return _Built(model, time, wait, active, route, corridor, ride, unserved, constraints, len(resource_rows) + len(forbidden)), perf_counter() - started


def _extract(prepared, built):
    movement = prepared.problem.resolved_trajectory_problem.structural_movement_problem
    starts = {s.cabin_id: s for s in movement.starts}
    options = {o.id: o for o in movement.route_options}
    trajectories = []
    for cabin, states in prepared.states_by_cabin:
        visits = []
        start = starts[cabin]
        for visit in range(start.max_visit_count):
            if built.active[cabin, visit].X < 0.5:
                break
            selected = [o for c, v, o in built.route if c == cabin and v == visit and built.route[c, v, o].X > 0.5]
            if len(selected) != 1:
                raise ValueError("corridor extraction found no unique route")
            visits.append(build_ddd_reference_visit(
                start=start, visit_index=visit,
                switch_time_seconds=ddd_tick_to_seconds(round(built.time[cabin, visit].X)),
                option=options[selected[0]], operational_end_seconds=movement.operational_end_seconds,
                tolerance_seconds=0.0,
                wait_seconds=ddd_tick_to_seconds(round(built.wait[cabin, visit].X)),
            ))
        boundary = tuple(o for o in prepared.problem.boundary_context.resource_occurrences if o.cabin_id == cabin)
        trajectories.append(DddReferenceTrajectory(cabin, tuple(visits), boundary_resource_occurrences=boundary))
    solution = DddReferenceSolution(tuple(trajectories))
    return solution


def validate_corridor_passenger_assignment(
    prepared: CorridorPreparedProblem,
    solution: DddReferenceSolution,
    ride_counts: tuple[tuple[str, int], ...],
) -> int:
    """Validate integer direct rides against the original, unpartitioned domain."""
    problem = prepared.problem
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    candidates = {item.id: item for item in problem.passenger_build.ride_candidates}
    groups = {item.id: item for item in problem.passenger_build.demand_groups}
    visits = {
        (trajectory.cabin_id, visit.visit_index): visit
        for trajectory in solution.trajectories
        for visit in trajectory.visits
    }
    options = {item.id: item for item in movement.route_options}
    amounts: dict[str, int] = {}
    served_by_group = defaultdict(int)
    onboard = defaultdict(int)
    capacity = problem.artifact.config.cabin_capacity
    for ride_id, amount in ride_counts:
        if ride_id in amounts or ride_id not in candidates:
            raise ValueError("corridor passenger certificate has an unknown or duplicate ride")
        if type(amount) is not int or amount <= 0:
            raise ValueError("corridor passenger quantities must be positive integers")
        candidate = candidates[ride_id]
        group = groups[candidate.demand_group_id]
        board_key = (candidate.cabin_id, candidate.board_visit_index)
        alight_key = (candidate.cabin_id, candidate.alight_visit_index)
        if board_key not in visits or alight_key not in visits:
            raise ValueError("corridor passenger ride references an inactive visit")
        board_visit, alight_visit = visits[board_key], visits[alight_key]
        board_option = options[board_visit.route_option_id]
        alight_option = options[alight_visit.route_option_id]
        if (
            board_option.decision is not DddRouteDecision.STOP
            or alight_option.decision is not DddRouteDecision.STOP
        ):
            raise ValueError("corridor passengers may board and alight only on STOP")
        board_tick = (
            ddd_seconds_to_tick(board_visit.switch_time_seconds)
            + ddd_seconds_to_tick(board_option.platform_exit_offset_seconds)
            + ddd_seconds_to_tick(board_visit.wait_seconds)
        )
        alight_tick = (
            ddd_seconds_to_tick(alight_visit.switch_time_seconds)
            + ddd_seconds_to_tick(alight_option.platform_entry_offset_seconds)
        )
        if board_tick < ddd_seconds_to_tick(group.release_time_seconds):
            raise ValueError("corridor passenger boards before release")
        if board_tick > movement.passenger_service_end_tick or alight_tick > movement.passenger_service_end_tick:
            raise ValueError("corridor passenger is not delivered within the service horizon")
        if alight_tick < board_tick:
            raise ValueError("corridor passenger alights before boarding")
        amounts[ride_id] = amount
        served_by_group[group.id] += amount
        for visit_index in range(candidate.board_visit_index, candidate.alight_visit_index):
            onboard[candidate.cabin_id, visit_index] += amount
    if any(served_by_group[group.id] > group.count for group in groups.values()):
        raise ValueError("corridor passenger certificate exceeds demand")
    if any(value > capacity for value in onboard.values()):
        raise ValueError("corridor passenger certificate exceeds cabin capacity")
    return sum(group.count - served_by_group[group.id] for group in groups.values())


def optimize_corridor_seed_passengers(
    prepared: CorridorPreparedProblem,
    solution: DddReferenceSolution,
    *,
    time_limit_seconds: float = 30.0,
    threads: int | None = None,
) -> CorridorPassengerSeedResult:
    """Reoptimize integer direct rides on one independently valid movement plan."""
    if time_limit_seconds <= 0:
        raise ValueError("corridor seed passenger time limit must be positive")
    movement = prepared.problem.resolved_trajectory_problem.structural_movement_problem
    validate_ddd_reference_solution(
        movement, solution, waiting_policy=prepared.waiting_policy
    )
    visits = {
        (trajectory.cabin_id, visit.visit_index): visit
        for trajectory in solution.trajectories
        for visit in trajectory.visits
    }
    options = {item.id: item for item in movement.route_options}
    groups = {item.id: item for item in prepared.problem.passenger_build.demand_groups}
    capacity = prepared.problem.artifact.config.cabin_capacity
    model = gp.Model("corridor_seed_passengers")
    model.Params.OutputFlag = 0
    model.Params.TimeLimit = time_limit_seconds
    model.Params.MIPGap = 0
    if threads is not None:
        model.Params.Threads = threads
    ride_vars = {}
    by_group = defaultdict(list)
    onboard = defaultdict(list)
    for candidate in prepared.problem.passenger_build.ride_candidates:
        board_key = candidate.cabin_id, candidate.board_visit_index
        alight_key = candidate.cabin_id, candidate.alight_visit_index
        if board_key not in visits or alight_key not in visits:
            continue
        board_visit, alight_visit = visits[board_key], visits[alight_key]
        board_option = options[board_visit.route_option_id]
        alight_option = options[alight_visit.route_option_id]
        if (
            board_option.decision is not DddRouteDecision.STOP
            or alight_option.decision is not DddRouteDecision.STOP
        ):
            continue
        group = groups[candidate.demand_group_id]
        board_tick = (
            ddd_seconds_to_tick(board_visit.switch_time_seconds)
            + ddd_seconds_to_tick(board_option.platform_exit_offset_seconds)
            + ddd_seconds_to_tick(board_visit.wait_seconds)
        )
        alight_tick = (
            ddd_seconds_to_tick(alight_visit.switch_time_seconds)
            + ddd_seconds_to_tick(alight_option.platform_entry_offset_seconds)
        )
        if (
            board_tick < ddd_seconds_to_tick(group.release_time_seconds)
            or board_tick > movement.passenger_service_end_tick
            or alight_tick > movement.passenger_service_end_tick
            or alight_tick < board_tick
        ):
            continue
        variable = model.addVar(
            lb=0,
            ub=min(capacity, group.count),
            vtype=GRB.INTEGER,
            name=f"seed_ride[{candidate.id}]",
        )
        ride_vars[candidate.id] = variable
        by_group[group.id].append(variable)
        for visit_index in range(candidate.board_visit_index, candidate.alight_visit_index):
            onboard[candidate.cabin_id, visit_index].append(variable)
    unserved = {}
    for group in groups.values():
        variable = model.addVar(lb=0, ub=group.count, vtype=GRB.INTEGER)
        unserved[group.id] = variable
        model.addConstr(gp.quicksum(by_group[group.id]) + variable == group.count)
    for variables in onboard.values():
        model.addConstr(gp.quicksum(variables) <= capacity)
    model.setObjective(gp.quicksum(unserved.values()), GRB.MINIMIZE)
    started = perf_counter()
    model.optimize()
    elapsed = perf_counter() - started
    if model.SolCount == 0:
        raise RuntimeError("corridor fixed-movement passenger IP found no assignment")
    rides = tuple(sorted(
        (ride_id, round(variable.X))
        for ride_id, variable in ride_vars.items()
        if variable.X > 0.5
    ))
    objective = validate_corridor_passenger_assignment(prepared, solution, rides)
    if objective != round(model.ObjVal):
        raise RuntimeError("corridor fixed-movement passenger objective mismatch")
    DddFixedKPrimalValidator().validate(
        prepared.problem,
        solution,
        dict(rides),
        provenance="corridor_seed_passenger_ip",
    )
    return CorridorPassengerSeedResult(
        rides,
        objective,
        model.Status == GRB.OPTIMAL,
        elapsed,
    )


@dataclass(slots=True)
class CorridorArcFlowOptimizer:
    config: CorridorArcFlowSolveConfig = CorridorArcFlowSolveConfig()

    def solve(
        self,
        prepared: CorridorPreparedProblem,
        *,
        seed: DddReferenceSolution | None = None,
        seed_ride_counts: dict[str, int] | None = None,
    ):
        total = perf_counter()
        self.config.validate()
        built, build_seconds = _build(prepared, self.config, seed, seed_ride_counts)
        solve_started = perf_counter()
        progress: list[CorridorArcFlowProgress] = []
        last_bound_bucket = None
        last_sample_second = -1

        def callback(model: gp.Model, where: int) -> None:
            nonlocal last_bound_bucket, last_sample_second
            try:
                if where == GRB.Callback.MIPSOL:
                    incumbent = float(model.cbGet(GRB.Callback.MIPSOL_OBJ))
                    bound = float(model.cbGet(GRB.Callback.MIPSOL_OBJBND))
                    progress.append(CorridorArcFlowProgress(
                        "incumbent",
                        float(model.cbGet(GRB.Callback.RUNTIME)),
                        incumbent if math.isfinite(incumbent) else None,
                        bound if math.isfinite(bound) and abs(bound) < 1e90 else None,
                        float(model.cbGet(GRB.Callback.MIPSOL_NODCNT)),
                    ))
                elif where == GRB.Callback.MIP:
                    elapsed = float(model.cbGet(GRB.Callback.RUNTIME))
                    bound = float(model.cbGet(GRB.Callback.MIP_OBJBND))
                    second = int(elapsed // 2)
                    bucket = None if not math.isfinite(bound) or abs(bound) >= 1e90 else math.ceil(bound - 1e-6)
                    if second > last_sample_second or bucket != last_bound_bucket:
                        last_sample_second = second
                        last_bound_bucket = bucket
                        incumbent = float(model.cbGet(GRB.Callback.MIP_OBJBST))
                        progress.append(CorridorArcFlowProgress(
                            "bound",
                            elapsed,
                            incumbent if math.isfinite(incumbent) else None,
                            bound if math.isfinite(bound) else None,
                            float(model.cbGet(GRB.Callback.MIP_NODCNT)),
                        ))
            except gp.GurobiError:
                return

        built.model.optimize(callback)
        solve_seconds = perf_counter() - solve_started
        status = built.model.Status
        has_solution = built.model.SolCount > 0
        solution = None
        relaxed_candidate = None
        detail = None
        result_status = CorridorArcFlowStatus.UNKNOWN
        if has_solution:
            try:
                relaxed_candidate = _extract(prepared, built)
                ride_values = tuple(sorted(
                    (key, round(var.X)) for key, var in built.ride.items() if var.X > 0.5
                ))
                passenger_objective = validate_corridor_passenger_assignment(
                    prepared, relaxed_candidate, ride_values
                )
                checked = DddFixedKPrimalValidator().validate(
                    prepared.problem,
                    relaxed_candidate,
                    dict(ride_values),
                    provenance="corridor_arc_flow",
                )
                independently_unserved = sum(checked.unserved_counts.values())
                if independently_unserved != passenger_objective:
                    raise ValueError("shared fixed-K validator and corridor certificate differ")
                if passenger_objective != round(built.model.ObjVal):
                    raise ValueError("corridor passenger certificate objective differs from the model")
                validate_ddd_reference_solution(
                    prepared.problem.resolved_trajectory_problem.structural_movement_problem,
                    relaxed_candidate,
                    waiting_policy=prepared.waiting_policy,
                )
                solution = relaxed_candidate
                result_status = CorridorArcFlowStatus.OPTIMAL if status == GRB.OPTIMAL else CorridorArcFlowStatus.FEASIBLE
            except ValueError as error:
                detail = str(error)
                result_status = (
                    CorridorArcFlowStatus.RELAXED_FEASIBLE
                    if self.config.mode is CorridorArcFlowMode.OUTER
                    else CorridorArcFlowStatus.VALIDATION_ERROR
                )
        elif status == GRB.INFEASIBLE:
            result_status = CorridorArcFlowStatus.INFEASIBLE
        objective = round(built.model.ObjVal) if has_solution else None
        raw_bound = (
            float(built.model.ObjBound)
            if status not in (GRB.INFEASIBLE, GRB.INF_OR_UNBD) else None
        )
        bound = (
            raw_bound
            if raw_bound is not None and math.isfinite(raw_bound) and abs(raw_bound) < 1e90
            else None
        )
        certified = None
        if self.config.mode is CorridorArcFlowMode.OUTER and bound is not None:
            certified = max(0, math.ceil(bound - 1e-6))
        rides = tuple(sorted((key, round(var.X)) for key, var in built.ride.items() if has_solution and var.X > 0.5))
        selected_corridors = tuple(sorted(
            key for key, variable in built.corridor.items()
            if has_solution and variable.X > 0.5
        ))
        return CorridorArcFlowResult(
            result_status, self.config.mode, prepared.problem.fingerprint,
            prepared.model_fingerprint, objective, bound, certified, solution,
            relaxed_candidate, rides, selected_corridors,
            built.model.NumVars, built.model.NumConstrs + built.model.NumGenConstrs,
            len(prepared.arcs), built.resource_conflict_count, build_seconds,
            solve_seconds, perf_counter() - total, built.model.NodeCount,
            tuple(progress), detail,
        )
