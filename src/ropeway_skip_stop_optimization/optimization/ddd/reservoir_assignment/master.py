"""Load-aware Gurobi master without inter-cabin resource conflicts."""

from collections import defaultdict
from dataclasses import dataclass
import math
from time import perf_counter

import gurobipy as gp
from gurobipy import GRB

from ..cp_formulation import prepare_cp_structure
from ..models import DddRouteDecision
from ..route_topology import unique_stop_route_option
from ..time_ticks import ddd_seconds_to_tick as tick
from .assignment import (
    ReservoirServiceAssignment,
    ReservoirServiceTrip,
    validate_service_assignment,
)
from .conflicts import ReservoirAssignmentConflict


@dataclass(frozen=True)
class ReservoirAssignmentMasterConfig:
    target_served: int
    profile: str = "balanced"
    fleet_cap: int | None = None
    time_limit_seconds: float = 60.0
    threads: int = 12
    seed: int = 0
    soft_memory_gb: float = 24.0
    log_to_console: bool = False
    conflict_cuts: tuple[ReservoirAssignmentConflict, ...] = ()

    def validate(self, problem):
        demand = sum(g.count for g in problem.demand_groups)
        if type(self.target_served) is not int or not 0 <= self.target_served <= demand:
            raise ValueError("master target served is outside demand")
        if self.profile not in ("balanced", "total_work"):
            raise ValueError("unknown assignment load profile")
        cap = problem.available_fleet_count if self.fleet_cap is None else self.fleet_cap
        if type(cap) is not int or not 0 <= cap <= problem.available_fleet_count:
            raise ValueError("invalid assignment fleet cap")
        if not math.isfinite(self.time_limit_seconds) or self.time_limit_seconds <= 0:
            raise ValueError("invalid assignment master time limit")
        if type(self.threads) is not int or self.threads <= 0 or type(self.seed) is not int or self.seed < 0:
            raise ValueError("invalid assignment master workers/seed")
        if not math.isfinite(self.soft_memory_gb) or self.soft_memory_gb <= 0:
            raise ValueError("invalid assignment master memory limit")
        if any(cut.problem_fingerprint != problem.fingerprint for cut in self.conflict_cuts):
            raise ValueError("assignment conflict problem fingerprint mismatch")
        return cap


def _integer_change_indicator(model, expression, value, name, *, relation="eq"):
    changed = model.addVar(vtype=GRB.BINARY, name=f"changed[{name}]")
    if relation == "ge":
        model.addGenConstrIndicator(changed, False, expression >= value)
        model.addGenConstrIndicator(changed, True, expression <= value - 1)
        return changed
    lower = model.addVar(vtype=GRB.BINARY, name=f"changed_lower[{name}]")
    upper = model.addVar(vtype=GRB.BINARY, name=f"changed_upper[{name}]")
    model.addConstr(lower + upper == changed)
    model.addGenConstrIndicator(changed, False, expression == value)
    model.addGenConstrIndicator(lower, True, expression <= value - 1)
    model.addGenConstrIndicator(upper, True, expression >= value + 1)
    return changed


def _add_conflict_cut(model, problem, conflict, active, route, waits, counts, served):
    if conflict.problem_fingerprint != problem.fingerprint:
        raise ValueError("assignment conflict problem fingerprint mismatch")
    changes = []
    for position, assumption in enumerate(conflict.assumptions):
        name = f"{conflict.id[:12]}:{position}"
        if assumption.kind == "active":
            cabin, visit = map(int, assumption.key.split(":"))
            variable = active[cabin][visit]
            changes.append(variable if assumption.value == 0 else 1 - variable)
        elif assumption.kind == "route":
            cabin_text, visit_text, option_id = assumption.key.split(":", 2)
            variable = route[int(cabin_text), int(visit_text), option_id]
            changes.append(1 - variable)
        elif assumption.kind == "wait":
            cabin, visit = map(int, assumption.key.split(":"))
            changes.append(
                _integer_change_indicator(
                    model, waits[cabin, visit], assumption.value, name
                )
            )
        elif assumption.kind in ("ride_eq", "ride_ge"):
            variable = counts.get(assumption.key)
            if variable is None:
                if assumption.value:
                    raise ValueError("conflict references unavailable positive ride")
                continue
            changes.append(
                _integer_change_indicator(
                    model,
                    variable,
                    assumption.value,
                    name,
                    relation="ge" if assumption.kind == "ride_ge" else "eq",
                )
            )
        elif assumption.kind == "served_ge":
            if served is None:
                raise ValueError("conflict requires unavailable served expression")
            changes.append(
                _integer_change_indicator(
                    model, served, assumption.value, name, relation="ge"
                )
            )
        else:
            raise ValueError(f"unsupported assignment conflict kind: {assumption.kind}")
    if not changes:
        raise ValueError("assignment conflict has no variable master decision")
    model.addConstr(gp.quicksum(changes) >= 1, name=f"conflict[{conflict.id[:12]}]")


def _integer(value, label):
    result = round(value)
    if abs(value - result) > 1e-5:
        raise ValueError(f"nonintegral assignment value: {label}")
    return result


def _model_attribute(model, name):
    """Read a result attribute that some Gurobi objective modes omit."""
    try:
        value = model.getAttr(name)
    except (AttributeError, gp.GurobiError):
        return None
    return value if isinstance(value, (int, float)) and math.isfinite(value) else None


def _extend_reference_assignment(problem, plan, target_served, profile, excluded):
    """Build a valid master start by adding individually feasible spare trips."""
    if plan is None:
        return None
    from ..reservoir_cp_sat_certificate import (
        DddReservoirCpPlan,
        validate_reservoir_cp_plan,
    )

    metrics = validate_reservoir_cp_plan(problem, plan)
    if metrics.served > target_served:
        return None
    ride_counts = dict(plan.ride_counts)
    groups = {g.id: g for g in problem.demand_groups}
    options = {o.id: o for o in problem.resolved_core.route_options}
    candidates = problem.passenger_build.ride_candidates
    candidates_by_id = {q.id: q for q in candidates}
    rides_by_cabin = defaultdict(list)
    for rid, count in ride_counts.items():
        if count:
            rides_by_cabin[candidates_by_id[rid].cabin_id].append(
                candidates_by_id[rid]
            )

    def compressed_reference_trip(source):
        required = {
            index
            for q in rides_by_cabin[source.cabin_id]
            for index in (q.board_visit_index, q.alight_visit_index)
        }
        earliest_wait = tick(problem.waiting_policy.earliest_wait_time_seconds)
        first_waitable = len(source.route_option_ids)
        for i, oid in enumerate(source.route_option_ids):
            option = options[oid]
            if (
                option.decision is DddRouteDecision.STOP
                and source.switch_ticks[i]
                + tick(option.platform_exit_offset_seconds)
                >= earliest_wait
            ):
                first_waitable = i
                break
        selected = []
        for i in range(len(source.route_option_ids)):
            choices = problem.resolved_core.route_options_by_state_id[
                problem.visit_states[i]
            ]
            decision = (
                DddRouteDecision.STOP
                if i <= first_waitable or i in required
                else DddRouteDecision.SKIP
            )
            option = next((o for o in choices if o.decision is decision), None)
            if option is None:
                return None
            selected.append(option)
        anchors = [i for i, option in enumerate(selected) if option.decision is DddRouteDecision.STOP]
        waits = [0] * len(selected)
        for position, i in enumerate(anchors):
            next_index = anchors[position + 1] if position + 1 < len(anchors) else len(selected)
            target = (
                source.switch_ticks[next_index]
                if next_index < len(selected)
                else source.return_tick
            )
            path_duration = sum(o.duration_tick for o in selected[i:next_index])
            wait = target - source.switch_ticks[i] - path_duration
            if wait < 0:
                return None
            if wait:
                option = selected[i]
                if (
                    source.switch_ticks[i]
                    + tick(option.platform_exit_offset_seconds)
                    < earliest_wait
                    or wait
                    > tick(
                        problem.waiting_policy.maximum_wait_seconds(option.station_id)
                    )
                ):
                    return None
            waits[i] = wait
        switch = []
        now = source.switch_ticks[0]
        for option, wait in zip(selected, waits, strict=True):
            switch.append(now)
            now += option.duration_tick + wait
        result = ReservoirServiceTrip(
            source.cabin_id,
            tuple(o.id for o in selected),
            tuple(switch),
            tuple(waits),
            now,
        )
        try:
            validate_reservoir_cp_plan(
                problem,
                DddReservoirCpPlan(
                    (result.as_cp_trip(),),
                    {
                        rid: count
                        for rid, count in ride_counts.items()
                        if candidates_by_id[rid].cabin_id == source.cabin_id
                    },
                ),
            )
        except ValueError:
            return None
        return result

    trips = []
    for source in plan.trips:
        compressed = compressed_reference_trip(source)
        trips.append(
            compressed
            or ReservoirServiceTrip(
                source.cabin_id,
                source.route_option_ids,
                source.switch_ticks,
                source.wait_ticks,
                source.return_tick,
            )
        )
    if tuple(t.cabin_id for t in trips) != tuple(range(len(trips))):
        return None
    remaining = target_served - metrics.served
    if not remaining:
        result = ReservoirServiceAssignment(
            problem.fingerprint, target_served, tuple(trips), ride_counts, profile
        )
        validate_service_assignment(problem, result)
        return result
    unserved = dict(metrics.unserved_counts)

    def minimal_trip(candidate):
        states = problem.visit_states
        try:
            end = next(
                i
                for i in range(candidate.alight_visit_index + 1, len(states))
                if states[i] == problem.entry_state_id
            )
        except StopIteration:
            return None
        ids, relative = [], []
        now = 0
        for i in range(end):
            relative.append(now)
            options_at_state = problem.resolved_core.route_options_by_state_id[states[i]]
            decision = (
                DddRouteDecision.STOP
                if i in (candidate.board_visit_index, candidate.alight_visit_index)
                else DddRouteDecision.SKIP
            )
            selected = next((o for o in options_at_state if o.decision is decision), None)
            if selected is None:
                return None
            ids.append(selected.id)
            now += selected.duration_tick
        board = options[ids[candidate.board_visit_index]]
        alight = options[ids[candidate.alight_visit_index]]
        group = groups[candidate.demand_group_id]
        relative_departure = (
            relative[candidate.board_visit_index]
            + tick(board.platform_exit_offset_seconds)
        )
        first = tick(problem.dispatch_start_seconds)
        last = tick(problem.dispatch_end_seconds)
        grid = tick(problem.dispatch_step_seconds)
        earliest = max(first, tick(group.release_time_seconds) - relative_departure)
        dispatch = first + max(0, (earliest - first + grid - 1) // grid) * grid
        arrival = (
            dispatch
            + relative[candidate.alight_visit_index]
            + tick(alight.platform_entry_offset_seconds)
        )
        if (
            dispatch > last
            or arrival > problem.resolved_core.passenger_service_end_tick
            or dispatch + now > problem.resolved_core.operational_end_tick
            or dispatch + now < tick(problem.return_start_seconds)
        ):
            return None
        return ReservoirServiceTrip(
            candidate.cabin_id,
            tuple(ids),
            tuple(dispatch + value for value in relative),
            (0,) * end,
            dispatch + now,
        )

    for cabin in range(len(trips), problem.available_fleet_count):
        chosen = None
        for candidate in candidates:
            if (
                candidate.cabin_id != cabin
                or candidate.id in excluded
                or unserved.get(candidate.demand_group_id, 0) <= 0
            ):
                continue
            new_trip = minimal_trip(candidate)
            if new_trip is not None:
                chosen = candidate, new_trip
                break
        if chosen is None:
            break
        candidate, new_trip = chosen
        count = min(
            remaining,
            problem.cabin_capacity,
            unserved[candidate.demand_group_id],
        )
        ride_counts[candidate.id] = count
        unserved[candidate.demand_group_id] -= count
        remaining -= count
        trips.append(new_trip)
        if not remaining:
            result = ReservoirServiceAssignment(
                problem.fingerprint,
                target_served,
                tuple(trips),
                ride_counts,
                profile,
            )
            validate_service_assignment(problem, result)
            return result
    return None


def solve_assignment_master(
    problem, config=ReservoirAssignmentMasterConfig(0), *, reference_plan=None
):
    """Choose rides/routes with exact individual timing and approximate shared load."""
    problem.validate()
    fleet_cap = config.validate(problem)
    started = perf_counter()
    core = problem.resolved_core
    states = problem.visit_states
    visit_count = len(states) - 1
    options_by_state = core.route_options_by_state_id
    stop_by_state = {
        state: unique_stop_route_option(problem.movement, state, error_context="assignment master")
        for state in states[:-1]
    }
    step = tick(problem.waiting_policy.step_seconds or 0.000001)
    horizon = core.operational_end_tick
    service_end = core.passenger_service_end_tick
    dispatch_first = tick(problem.dispatch_start_seconds)
    dispatch_last = tick(problem.dispatch_end_seconds)
    dispatch_step = tick(problem.dispatch_step_seconds)
    return_start = tick(problem.return_start_seconds)
    model = gp.Model("reservoir_load_aware_assignment")
    model.Params.OutputFlag = int(config.log_to_console)
    model.Params.TimeLimit = config.time_limit_seconds
    model.Params.Threads = config.threads
    model.Params.Seed = config.seed
    model.Params.SoftMemLimit = config.soft_memory_gb

    y, active, route, times, waits, dispatches = {}, {}, {}, {}, {}, {}
    resource_terms = defaultdict(list)
    for k in range(problem.available_fleet_count):
        y[k] = model.addVar(vtype=GRB.BINARY, name=f"used[{k}]")
        if k:
            model.addConstr(y[k] <= y[k - 1], name=f"used_prefix[{k}]")
        active[k] = [model.addVar(vtype=GRB.BINARY, name=f"active[{k},{i}]") for i in range(len(states))]
        times[k] = [model.addVar(vtype=GRB.INTEGER, lb=0, ub=horizon, name=f"time[{k},{i}]") for i in range(len(states))]
        model.addConstr(active[k][0] == y[k], name=f"used_active[{k}]")
        model.addConstr(active[k][-1] == 0, name=f"terminal_inactive[{k}]")
        dispatch = model.addVar(
            vtype=GRB.INTEGER,
            lb=0,
            ub=(dispatch_last - dispatch_first) // dispatch_step,
            name=f"dispatch_step[{k}]",
        )
        dispatches[k] = dispatch
        model.addGenConstrIndicator(y[k], True, times[k][0] == dispatch_first + dispatch_step * dispatch)
        model.addGenConstrIndicator(y[k], False, times[k][0] == 0)
        model.addGenConstrIndicator(y[k], False, dispatch == 0)
        for i, state in enumerate(states):
            if i:
                model.addConstr(active[k][i] <= active[k][i - 1], name=f"active_prefix[{k},{i}]")
                if state != problem.entry_state_id:
                    model.addConstr(active[k][i] == active[k][i - 1], name=f"return_only_at_port[{k},{i}]")
                else:
                    returned = model.addVar(vtype=GRB.BINARY, name=f"returned[{k},{i}]")
                    model.addConstr(returned == active[k][i - 1] - active[k][i])
                    model.addGenConstrIndicator(returned, True, times[k][i] >= return_start)
            if i == visit_count:
                continue
            choices = options_by_state[state]
            for option in choices:
                route[k, i, option.id] = model.addVar(
                    vtype=GRB.BINARY, name=f"route[{k},{i},{option.id}]"
                )
            model.addConstr(
                gp.quicksum(route[k, i, o.id] for o in choices) == active[k][i],
                name=f"one_route[{k},{i}]",
            )
            maxima = {
                o.id: tick(problem.waiting_policy.maximum_wait_seconds(o.station_id)) // step
                if o.decision is DddRouteDecision.STOP
                else 0
                for o in choices
            }
            maximum = max(maxima.values())
            waits[k, i] = model.addVar(
                vtype=GRB.INTEGER, lb=0, ub=maximum, name=f"wait_steps[{k},{i}]"
            )
            model.addConstr(
                waits[k, i]
                <= gp.quicksum(maxima[o.id] * route[k, i, o.id] for o in choices),
                name=f"wait_route[{k},{i}]",
            )
            if maximum:
                positive = model.addVar(vtype=GRB.BINARY, name=f"wait_positive[{k},{i}]")
                model.addConstr(waits[k, i] >= positive)
                model.addConstr(waits[k, i] <= maximum * positive)
                stop = stop_by_state[state]
                model.addConstr(positive <= route[k, i, stop.id])
                model.addGenConstrIndicator(
                    positive,
                    True,
                    times[k][i] + tick(stop.platform_exit_offset_seconds)
                    >= tick(problem.waiting_policy.earliest_wait_time_seconds),
                )
            model.addConstr(
                times[k][i + 1]
                == times[k][i]
                + gp.quicksum(o.duration_tick * route[k, i, o.id] for o in choices)
                + step * waits[k, i],
                name=f"time_chain[{k},{i}]",
            )
            wait_resource_coefficients = defaultdict(int)
            for option in choices:
                for usage in option.resource_usages:
                    separation = usage.separation_after_tick(
                        core.resources_by_id[usage.resource_id].minimum_headway_tick
                    )
                    fixed = (
                        usage.leader_clear_offset_tick
                        + separation
                        - usage.follower_enter_offset_tick
                    )
                    if fixed <= 0:
                        raise ValueError("assignment resource interval is not positive")
                    resource_terms[usage.resource_id].append(
                        fixed * route[k, i, option.id]
                    )
                    if option.decision is DddRouteDecision.STOP:
                        wait_resource_coefficients[usage.resource_id] += (
                            usage.leader_clear_wait_coefficient
                            - usage.follower_enter_wait_coefficient
                        )
            for rid, coefficient in wait_resource_coefficients.items():
                if coefficient:
                    resource_terms[rid].append(coefficient * step * waits[k, i])
    model.addConstr(gp.quicksum(y.values()) <= fleet_cap, name="fleet_cap")

    prepared = prepare_cp_structure(
        problem.movement,
        problem.passenger_build,
        {k: states for k in range(problem.available_fleet_count)},
        reservoir=problem,
    )
    ride_bounds = prepared.ride_map
    excluded = {rid for rid, bound in ride_bounds.items() if bound.exclusion}
    groups = {g.id: g for g in problem.demand_groups}
    counts, used = {}, {}
    by_group, onboard = defaultdict(list), defaultdict(list)
    for candidate in problem.passenger_build.ride_candidates:
        if ride_bounds[candidate.id].exclusion:
            continue
        group = groups[candidate.demand_group_id]
        upper = min(problem.cabin_capacity, group.count)
        q = model.addVar(vtype=GRB.INTEGER, lb=0, ub=upper, name=f"passengers[{candidate.id}]")
        z = model.addVar(vtype=GRB.BINARY, name=f"ride_used[{candidate.id}]")
        counts[candidate.id], used[candidate.id] = q, z
        model.addConstr(q >= z)
        model.addConstr(q <= upper * z)
        k, board, alight = (
            candidate.cabin_id,
            candidate.board_visit_index,
            candidate.alight_visit_index,
        )
        board_stop = stop_by_state[states[board]]
        alight_stop = stop_by_state[states[alight]]
        model.addConstr(z <= route[k, board, board_stop.id])
        model.addConstr(z <= route[k, alight, alight_stop.id])
        board_time = times[k][board] + tick(board_stop.platform_exit_offset_seconds) + step * waits[k, board]
        alight_time = times[k][alight] + tick(alight_stop.platform_entry_offset_seconds)
        model.addGenConstrIndicator(z, True, board_time >= tick(group.release_time_seconds))
        model.addGenConstrIndicator(z, True, board_time <= service_end)
        model.addGenConstrIndicator(z, True, alight_time <= service_end)
        model.addGenConstrIndicator(z, True, alight_time >= board_time)
        by_group[group.id].append(q)
        for i in range(board, alight):
            onboard[k, i].append(q)
    for group in groups.values():
        model.addConstr(gp.quicksum(by_group[group.id]) <= group.count, name=f"demand[{group.id}]")
    for (k, i), values in onboard.items():
        model.addConstr(
            gp.quicksum(values) <= problem.cabin_capacity * active[k][i],
            name=f"capacity[{k},{i}]",
        )
    served_expression = gp.quicksum(counts.values())
    model.addConstr(served_expression == config.target_served, name="target_served")
    for conflict in config.conflict_cuts:
        _add_conflict_cut(
            model,
            problem,
            conflict,
            active,
            route,
            waits,
            counts,
            served_expression,
        )

    loads = {}
    for resource in core.resources:
        expression = gp.quicksum(resource_terms[resource.id])
        loads[resource.id] = model.addVar(vtype=GRB.CONTINUOUS, lb=0, name=f"load[{resource.id}]")
        model.addConstr(loads[resource.id] == expression)
    maximum_load = model.addVar(vtype=GRB.CONTINUOUS, lb=0, name="maximum_resource_load")
    for rid, load in loads.items():
        model.addConstr(maximum_load >= load, name=f"maximum_load[{rid}]")
    total_load = gp.quicksum(loads.values())
    if config.profile == "balanced":
        model.ModelSense = GRB.MINIMIZE
        model.setObjectiveN(maximum_load, 0, priority=2, name="balanced_maximum")
        model.setObjectiveN(total_load, 1, priority=1, name="total_work")
    else:
        model.setObjective(total_load, GRB.MINIMIZE)
    master_start = _extend_reference_assignment(
        problem,
        reference_plan,
        config.target_served,
        config.profile,
        excluded,
    )
    if master_start is not None:
        start_trips = {t.cabin_id: t for t in master_start.trips}
        for k in range(problem.available_fleet_count):
            service_trip = start_trips.get(k)
            n = 0 if service_trip is None else len(service_trip.route_option_ids)
            y[k].Start = int(service_trip is not None)
            dispatches[k].Start = (
                0
                if service_trip is None
                else (service_trip.witness_switch_ticks[0] - dispatch_first)
                // dispatch_step
            )
            for i in range(len(states)):
                active[k][i].Start = int(i < n)
                times[k][i].Start = (
                    0
                    if service_trip is None
                    else service_trip.witness_switch_ticks[i]
                    if i < n
                    else service_trip.witness_return_tick
                )
                if i == visit_count:
                    continue
                waits[k, i].Start = (
                    0 if i >= n else service_trip.witness_wait_ticks[i] // step
                )
                selected = None if i >= n else service_trip.route_option_ids[i]
                for option in options_by_state[states[i]]:
                    route[k, i, option.id].Start = int(option.id == selected)
        for rid, variable in counts.items():
            value = master_start.ride_counts.get(rid, 0)
            variable.Start = value
            used[rid].Start = int(value > 0)
        model.Params.StartNodeLimit = 1000
    model.update()
    raw_stats = {
        "variables": model.NumVars,
        "constraints": model.NumConstrs,
        "nonzeros": model.NumNZs,
        "ride_variables": len(counts),
        "route_variables": len(route),
        "time_variables": sum(map(len, times.values())),
    }
    model.Params.TimeLimit = max(
        0.001, config.time_limit_seconds - (perf_counter() - started)
    )
    model.optimize()
    status = model.Status
    assignment = None
    validation = None
    if model.SolCount:
        trips = []
        for k in range(problem.available_fleet_count):
            if _integer(y[k].X, f"used[{k}]") == 0:
                continue
            n = sum(_integer(active[k][i].X, f"active[{k},{i}]") for i in range(visit_count))
            ids = []
            for i in range(n):
                selected = [o.id for o in options_by_state[states[i]] if _integer(route[k, i, o.id].X, "route")]
                if len(selected) != 1:
                    raise ValueError("assignment extraction has no unique route")
                ids.append(selected[0])
            trips.append(
                ReservoirServiceTrip(
                    k,
                    tuple(ids),
                    tuple(_integer(times[k][i].X, "time") for i in range(n)),
                    tuple(step * _integer(waits[k, i].X, "wait") for i in range(n)),
                    _integer(times[k][n].X, "return"),
                )
            )
        ride_counts = {
            rid: _integer(variable.X, rid)
            for rid, variable in counts.items()
            if _integer(variable.X, rid) > 0
        }
        assignment = ReservoirServiceAssignment(
            problem.fingerprint,
            config.target_served,
            tuple(trips),
            ride_counts,
            config.profile,
        )
        validation = validate_service_assignment(problem, assignment)
    result = {
        "schema": "reservoir_assignment_master_result_v1",
        "status": model.Status,
        "status_name": {
            GRB.OPTIMAL: "OPTIMAL",
            GRB.TIME_LIMIT: "TIME_LIMIT",
            GRB.INFEASIBLE: "INFEASIBLE",
            GRB.MEM_LIMIT: "MEM_LIMIT",
        }.get(status, str(status)),
        "has_assignment": assignment is not None,
        "target_served": config.target_served,
        "conflict_cut_count": len(config.conflict_cuts),
        "profile": config.profile,
        "fleet_cap": fleet_cap,
        # Multi-objective Gurobi models do not expose every scalar MIP
        # attribute.  Resource loads below are the portable result record.
        "objective": None if not model.SolCount else _model_attribute(model, "ObjVal"),
        "best_bound": _model_attribute(model, "ObjBound"),
        "gap": None if not model.SolCount else _model_attribute(model, "MIPGap"),
        "node_count": model.NodeCount,
        "runtime_seconds": model.Runtime,
        "total_seconds": perf_counter() - started,
        "model_stats": raw_stats,
        "validation": validation,
        "master_start": None
        if master_start is None
        else {
            "served": master_start.target_served,
            "used_fleet": len(master_start.trips),
            "fingerprint": master_start.fingerprint,
        },
        "returned_master_start_unchanged": master_start is not None
        and assignment is not None
        and master_start.fingerprint == assignment.fingerprint,
        "resource_loads": None if not model.SolCount else {rid: load.X for rid, load in loads.items()},
    }
    model.dispose()
    return result, assignment
