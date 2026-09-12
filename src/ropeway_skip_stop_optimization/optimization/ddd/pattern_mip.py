"""Direct fixed-route MIP: integer microsecond timing, optional resource orders.

Selected route only is built for each visit. No time discretization relaxation,
no fixed visit prefix, no fixed resource order and no journey-time products.
"""

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from time import perf_counter

import gurobipy as gp
from gurobipy import GRB

from .cp_sat_certificate import (
    validate_ddd_cp_sat_domain,
    stable_fingerprint,
    solution_from_cp_sat_payload,
)
from .cp_sat_movement import _deterministic_visit_structure
from .fixed_timetable_capacity import conservative_count_bound
from .models import DddRouteDecision
from .pattern_oracle_probe import PatternProbeConfig, ProbeProgress
from .pattern_search import unserved
from .time_ticks import ddd_seconds_to_tick as tick


@dataclass
class PatternMipModel:
    model: object
    times: dict
    active: dict
    waits: dict
    quantities: dict
    routes: dict
    step: int
    stats: dict

    def extract(self, problem, value):
        supports = []
        cabins = sorted({c for c, v in self.routes})
        for c in cabins:
            choices = []
            times = []
            waits = []
            for v in range(sum(k == c for k, i in self.routes)):
                if round(value(self.active[c, v])) == 0:
                    break
                choices.append(self.routes[c, v].id)
                times.append(int(round(value(self.times[c, v]))))
                waits.append(int(round(value(self.waits[c, v]))) * self.step)
            supports.append(
                dict(
                    cabin_id=c,
                    route_option_ids=choices,
                    switch_times_tick=times,
                    wait_ticks=waits,
                )
            )
        counts = {
            q: int(round(value(x)))
            for q, x in self.quantities.items()
            if value(x) > 0.5
        }
        return solution_from_cp_sat_payload(
            problem, dict(trajectory_supports=supports)
        ), counts


def build_pattern_mip(problem, pattern, *, log_file=None, deadline=None, seed=None):
    manifest = validate_ddd_cp_sat_domain(problem)
    if pattern.domain_id != stable_fingerprint(manifest):
        raise ValueError("pattern domain mismatch")
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    waiting = problem.resolved_trajectory_problem.waiting_policy
    step = 1 if waiting.step_seconds is None else tick(waiting.step_seconds)
    if tuple(sorted(pattern.choices)) != pattern.choices:
        raise ValueError("pattern must be sorted")
    choices = {(c, v): o for c, v, o in pattern.choices}
    if len(choices) != len(pattern.choices):
        raise ValueError("duplicate pattern visits")
    options = {o.id: o for o in movement.route_options}
    horizon = movement.operational_end_tick
    service = movement.passenger_service_end_tick
    maximum = horizon + max(
        o.duration_tick + tick(waiting.maximum_wait_seconds(o.station_id))
        for o in movement.route_options
    )
    model = gp.Model("fixed_pattern_capacity")
    model.Params.OutputFlag = 0 if log_file is None else 1
    model.Params.LogToConsole = 0
    if log_file:
        model.Params.LogFile = str(log_file)
    model.Params.IntFeasTol = 1e-9
    model.Params.FeasibilityTol = 1e-9
    model.Params.IntegralityFocus = 1
    model.Params.MIPGap = 0
    model.Params.MIPGapAbs = 0
    times, active, waits, routes, earliest = {}, {}, {}, {}, {}
    intervals = defaultdict(list)
    required = set()
    hint_times, hint_waits, hint_active = {}, {}, {}
    seed_visits = (
        {}
        if seed is None
        else {t.cabin_id: t.visits for t in seed.solution.trajectories}
    )
    if seed is not None and not pattern.matches(seed.solution):
        raise ValueError("MIP seed must match the pattern")

    def guard():
        if deadline is not None and perf_counter() >= deadline:
            model.dispose()
            raise TimeoutError("fixed-pattern MIP build budget exhausted")

    for start in sorted(movement.starts, key=lambda s: s.cabin_id):
        guard()
        c = start.cabin_id
        states, os_by_visit = _deterministic_visit_structure(
            movement, start.state_id, start.max_visit_count
        )
        lower = start.time_tick
        for v in range(start.max_visit_count + 1):
            key = c, v
            earliest[key] = lower
            times[key] = model.addVar(
                lb=start.time_tick if v == 0 else min(lower, horizon + 1),
                ub=start.time_tick if v == 0 else maximum,
                vtype=GRB.INTEGER,
                name=f"t[{c},{v}]",
            )
            active[key] = model.addVar(
                lb=1 if v == 0 else 0,
                ub=0 if v == start.max_visit_count or lower > horizon else 1,
                vtype=GRB.BINARY,
                name=f"a[{c},{v}]",
            )
            if seed is not None:
                seq = seed_visits[c]
                hint_times[key] = tick(
                    seq[v].switch_time_seconds
                    if v < len(seq)
                    else seq[-1].next_switch_time_seconds
                )
                hint_active[key] = int(v < len(seq))
                hint_waits[key] = (
                    tick(seq[v].wait_seconds) // step if v < len(seq) else 0
                )
                times[key].Start = hint_times[key]
                active[key].Start = hint_active[key]
            model.addGenConstrIndicator(active[key], True, times[key] <= horizon)
            model.addGenConstrIndicator(active[key], False, times[key] >= horizon + 1)
            if v < start.max_visit_count:
                required.add(key)
                if choices.get(key) not in {o.id for o in os_by_visit[v]}:
                    raise ValueError("invalid or missing pattern route")
                o = options[choices[key]]
                routes[key] = o
                lower += o.duration_tick
    if set(choices) != required:
        raise ValueError("pattern must cover complete structural domain")
    for key, o in routes.items():
        guard()
        c, v = key
        t = times[key]
        a = active[key]
        max_wait = (
            tick(waiting.maximum_wait_seconds(o.station_id)) // step
            if o.decision is DddRouteDecision.STOP
            and o.platform_exit_offset_seconds is not None
            else 0
        )
        w = model.addVar(lb=0, ub=max_wait, vtype=GRB.INTEGER, name=f"w[{c},{v}]")
        waits[key] = w
        if seed is not None:
            w.Start = hint_waits[key]
        model.addConstr(w <= max_wait * a)
        if max_wait and waiting.earliest_wait_time_seconds > 0:
            positive = model.addVar(vtype=GRB.BINARY)
            if seed is not None:
                positive.Start = int(hint_waits[key] > 0)
            model.addConstr(w >= positive)
            model.addConstr(w <= max_wait * positive)
            model.addGenConstrIndicator(
                positive,
                True,
                t + tick(o.platform_exit_offset_seconds)
                >= tick(waiting.earliest_wait_time_seconds),
            )
        model.addConstr(times[c, v + 1] == t + o.duration_tick * a + step * w)
        if earliest[key] > horizon:
            continue
        for j, u in enumerate(o.resource_usages):
            resource = movement.resources_by_id[u.resource_id]
            sep = u.separation_after_tick(resource.minimum_headway_tick)
            enter = (
                t
                + u.follower_enter_offset_tick
                + u.follower_enter_wait_coefficient * step * w
            )
            end = (
                t
                + u.leader_clear_offset_tick
                + sep
                + u.leader_clear_wait_coefficient * step * w
            )
            size = u.leader_clear_offset_tick + sep - u.follower_enter_offset_tick
            if (
                min(
                    size,
                    size
                    + (
                        u.leader_clear_wait_coefficient
                        - u.follower_enter_wait_coefficient
                    )
                    * step
                    * max_wait,
                )
                <= 0
            ):
                raise ValueError("resource interval must stay positive")
            hs = (
                None
                if seed is None
                else hint_times[key]
                + u.follower_enter_offset_tick
                + u.follower_enter_wait_coefficient * step * hint_waits[key]
            )
            he = (
                None
                if seed is None
                else hint_times[key]
                + u.leader_clear_offset_tick
                + sep
                + u.leader_clear_wait_coefficient * step * hint_waits[key]
            )
            hp = None if seed is None else int(hint_active[key] and hs <= horizon)
            emin = earliest[key] + u.follower_enter_offset_tick
            if emin > horizon:
                continue
            if (
                u.follower_enter_offset_tick == 0
                and u.follower_enter_wait_coefficient == 0
            ):
                present = a
            else:
                present = model.addVar(vtype=GRB.BINARY, name=f"p[{c},{v},{j}]")
                if seed is not None:
                    present.Start = hp
                model.addConstr(present <= a)
                model.addGenConstrIndicator(present, True, enter <= horizon)
                # Active but absent iff resource entry is beyond the operational horizon.
                model.addGenConstrIndicator(
                    present,
                    False,
                    enter >= horizon + 1 - (horizon + 1 - emin) * (1 - a),
                )
            intervals[u.resource_id].append(
                (
                    enter,
                    end,
                    present,
                    emin,
                    horizon,
                    earliest[key] + u.leader_clear_offset_tick + sep,
                    horizon
                    + u.leader_clear_offset_tick
                    + sep
                    + u.leader_clear_wait_coefficient * step * max_wait,
                    hs,
                    he,
                    hp,
                )
            )
    for occurrence in problem.boundary_context.resource_occurrences:
        resource = movement.resources_by_id[occurrence.resource_id]
        s = max(0, tick(occurrence.follower_enter_time_seconds))
        e = tick(
            occurrence.leader_clear_time_seconds
        ) + occurrence.separation_after_tick(resource)
        if e > s:
            intervals[occurrence.resource_id].append((s, e, 1, s, s, e, e, s, e, 1))
    pairs = orders = forced = 0
    for occurrences in intervals.values():
        for ia, ib in combinations(occurrences, 2):
            if pairs % 1000 == 0:
                guard()
            sa, ea, pa, samin, samax, eamin, eamax, hsa, hea, hpa = ia
            sb, eb, pb, sbmin, sbmax, ebmin, ebmax, hsb, heb, hpb = ib
            if eamax <= sbmin or ebmax <= samin:
                continue
            pairs += 1
            ab_possible = eamin <= sbmax
            ba_possible = ebmin <= samax
            if not ab_possible and not ba_possible:
                model.addConstr(pa + pb <= 1)
                forced += 1
                continue
            # Direction literals are active only if both intervals are present.
            ab = model.addVar(vtype=GRB.BINARY, ub=int(ab_possible))
            ba = model.addVar(vtype=GRB.BINARY, ub=int(ba_possible))
            if seed is not None:
                both = hpa and hpb
                hab = int(both and hea <= hsb)
                hba = int(both and not hab and heb <= hsa)
                if both and not (hab or hba):
                    raise ValueError("seed resource order conflict")
                ab.Start, ba.Start = hab, hba
            model.addConstr(ab + ba >= pa + pb - 1)
            model.addConstr(ab + ba <= pa)
            model.addConstr(ab + ba <= pb)
            if ab_possible:
                model.addGenConstrIndicator(ab, True, ea <= sb)
            if ba_possible:
                model.addGenConstrIndicator(ba, True, eb <= sa)
            orders += int(ab_possible) + int(ba_possible)
    groups = {g.id: g for g in problem.passenger_build.demand_groups}
    by_group, onboard = defaultdict(list), defaultdict(list)
    quantities = {}
    capacity = problem.artifact.config.cabin_capacity
    for q in problem.passenger_build.ride_candidates:
        b = (q.cabin_id, q.board_visit_index)
        a = (q.cabin_id, q.alight_visit_index)
        bo, ao = routes[b], routes[a]
        if (
            bo.decision is not DddRouteDecision.STOP
            or ao.decision is not DddRouteDecision.STOP
            or earliest[b] > horizon
            or earliest[a] > horizon
        ):
            continue
        group = groups[q.demand_group_id]
        count = model.addVar(
            lb=0, ub=min(group.count, capacity), vtype=GRB.INTEGER, name=f"y[{q.id}]"
        )
        used = model.addVar(vtype=GRB.BINARY)
        if seed is not None:
            count.Start = seed.ride_counts.get(q.id, 0)
            used.Start = int(seed.ride_counts.get(q.id, 0) > 0)
        model.addConstr(count >= used)
        model.addConstr(count <= min(group.count, capacity) * used)
        model.addConstr(used <= active[b])
        model.addConstr(used <= active[a])
        board = times[b] + tick(bo.platform_exit_offset_seconds) + step * waits[b]
        alight = times[a] + tick(ao.platform_entry_offset_seconds)
        for expr in (
            board >= max(0, tick(group.release_time_seconds)),
            board <= service,
            alight <= service,
            alight >= board,
        ):
            model.addGenConstrIndicator(used, True, expr)
        quantities[q.id] = count
        by_group[group.id].append(count)
        for v in range(q.board_visit_index, q.alight_visit_index):
            onboard[q.cabin_id, v].append(count)
    for g in groups.values():
        model.addConstr(gp.quicksum(by_group[g.id]) <= g.count)
    for counts in onboard.values():
        model.addConstr(gp.quicksum(counts) <= capacity)
    model.setObjective(
        sum(g.count for g in groups.values()) - gp.quicksum(quantities.values()),
        GRB.MINIMIZE,
    )
    model.update()
    return PatternMipModel(
        model,
        times,
        active,
        waits,
        quantities,
        routes,
        step,
        dict(
            variables=model.NumVars,
            hinted_variables=sum(
                x != GRB.UNDEFINED for x in model.getAttr("Start", model.getVars())
            ),
            binaries=model.NumBinVars,
            linear_constraints=model.NumConstrs,
            indicator_constraints=model.NumGenConstrs,
            resource_pairs=pairs,
            direction_literals=orders,
            incompatible_pairs=forced,
            ride_candidates=len(quantities),
        ),
    )


@dataclass
class FixedPatternMipProbe:
    config: PatternProbeConfig = PatternProbeConfig()

    def solve(
        self,
        problem,
        pattern,
        *,
        seed=None,
        event_callback=None,
        log_file=None,
        checkpoint=None,
    ):
        self.config.validate()
        started = perf_counter()
        progress = ProbeProgress(
            problem, pattern, seed, started, event_callback, checkpoint
        )
        try:
            built = build_pattern_mip(
                problem,
                pattern,
                log_file=log_file,
                deadline=started + self.config.seconds,
                seed=progress.best,
            )
        except TimeoutError:
            return progress.result(
                backend="gurobi",
                status="BUILD_TIME_LIMIT",
                lower=None,
                stats={},
                build_seconds=perf_counter() - started,
                solve_seconds=0,
                domain_manifest=validate_ddd_cp_sat_domain(problem),
            )
        model = built.model
        try:
            model.Params.Threads = self.config.workers
            model.Params.Seed = self.config.seed
            if progress.best is not None:
                model.addConstr(model.getObjective() <= unserved(progress.best))
            build_seconds = perf_counter() - started
            progress.emit(
                "model_built", model_stats=built.stats, build_seconds=build_seconds
            )
            errors = []
            bound_seen = [None]

            def callback(m, where):
                try:
                    if where == GRB.Callback.MIPSOL:
                        solution, counts = built.extract(
                            problem, lambda v: m.cbGetSolution(v)
                        )
                        progress.accept(solution, counts)
                    if where == GRB.Callback.MIP:
                        bound = conservative_count_bound(
                            m.cbGet(GRB.Callback.MIP_OBJBND)
                        )
                        if bound != bound_seen[0]:
                            bound_seen[0] = bound
                            progress.emit("bound", lower_bound=bound)
                except Exception as exc:
                    errors.append(exc)
                    m.terminate()

            remaining = self.config.seconds - build_seconds
            before = perf_counter()
            if remaining > 0:
                model.Params.TimeLimit = remaining
                model.optimize(callback)
                if errors:
                    raise RuntimeError("MIP certificate callback failed") from errors[0]
                status = {
                    GRB.OPTIMAL: "OPTIMAL",
                    GRB.INFEASIBLE: "INFEASIBLE",
                    GRB.TIME_LIMIT: "TIME_LIMIT",
                }.get(model.Status, str(model.Status))
                lower = (
                    conservative_count_bound(model.ObjBound)
                    if model.Status not in (GRB.INFEASIBLE, GRB.INF_OR_UNBD)
                    else None
                )
                if model.SolCount:
                    solution, counts = built.extract(problem, lambda v: v.X)
                    progress.accept(solution, counts)
                if model.Status == GRB.OPTIMAL:
                    lower = unserved(progress.best)
            else:
                status = "BUILD_TIME_LIMIT"
                lower = None
            return progress.result(
                backend="gurobi",
                status=status,
                lower=lower,
                stats=built.stats,
                build_seconds=build_seconds,
                solve_seconds=perf_counter() - before,
                domain_manifest=validate_ddd_cp_sat_domain(problem),
            )
        finally:
            model.dispose()
