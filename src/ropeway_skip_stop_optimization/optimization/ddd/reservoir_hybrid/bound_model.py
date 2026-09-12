"""Continuous global relaxation with explicit shared passenger capacity."""

from collections import defaultdict
from dataclasses import dataclass
from time import perf_counter
import math

import gurobipy as gp
from gurobipy import GRB

from ..cp_sat_certificate import stable_fingerprint
from ..models import DddRouteDecision
from ..time_ticks import ddd_seconds_to_tick as tick
from ..reservoir_cp_sat_certificate import validate_reservoir_cp_plan
from .bound_domain import check_deadline, minimum_overlap
from .certificates import GlobalReservoirBound

PROFILES = ("arrival_only", "movement_capacity", "resource_windows")


class BoundSizeLimit(RuntimeError):
    def __init__(self, message, *, variable_families=None, row_families=None):
        super().__init__(message)
        self.variable_families = variable_families or {}
        self.row_families = row_families or {}


def analytical_bound(problem):
    """Release + direct minimum ride time, with unserved as an alternative."""
    options = problem.resolved_core.route_options_by_state_id
    stops = {
        o.station_id: o
        for o in problem.resolved_core.route_options
        if o.decision is DddRouteDecision.STOP
    }
    result = 0
    for g in problem.demand_groups:
        o = stops[g.origin_station_id]
        destination = stops[g.destination_station_id]
        duration = o.duration_tick - tick(o.platform_exit_offset_seconds)
        state = o.to_state_id
        while state != destination.from_state_id:
            duration += min(q.duration_tick for q in options[state])
            state = options[state][0].to_state_id
        duration += tick(destination.platform_entry_offset_seconds)
        result += g.count * min(
            duration,
            problem.resolved_core.passenger_service_end_tick
            - tick(g.release_time_seconds),
        )
    return result / 1e6


@dataclass
class ReservoirArrivalBoundModel:
    prepared: object
    model: object
    variables: dict
    profile: str
    row_families: dict
    build_seconds: float
    fingerprint: str
    journey_encoding: str = "legacy"
    objective: str = "journey_time"

    def project(self, plan, tolerance=1e-5):
        """Check the original independent certificate against every built row."""
        p = self.prepared.problem
        metrics = validate_reservoir_cp_plan(p, plan)
        part = self.prepared.partition
        index = {
            (a.visit, a.source, a.target, a.option_id): a for a in self.prepared.arcs
        }
        values = defaultdict(float)
        trip_arcs = {}
        for trip in plan.trips:
            values[("dispatch", 0, part.cell(trip.switch_ticks[0]))] += 1
            values[
                ("return", len(trip.route_option_ids), part.cell(trip.return_tick))
            ] += 1
            for i, (oid, t) in enumerate(zip(trip.route_option_ids, trip.switch_ticks)):
                next_t = (
                    trip.switch_ticks[i + 1]
                    if i + 1 < len(trip.switch_ticks)
                    else trip.return_tick
                )
                key = i, part.cell(t), part.cell(next_t), oid
                if key not in index:
                    raise ValueError(f"original movement absent from bound: {key}")
                a = index[key]
                trip_arcs[trip.cabin_id, i] = a.id
                values["x", a.id] += 1
        rides = {r.id: r for r in p.passenger_build.ride_candidates}
        for rid, n in plan.ride_counts.items():
            r = rides[rid]
            if self.profile == "arrival_only":
                values["served", r.demand_group_id] += n
                continue
            for i in range(r.board_visit_index, r.alight_visit_index + 1):
                key = (
                    "f",
                    r.demand_group_id,
                    r.board_visit_index,
                    trip_arcs[r.cabin_id, i],
                )
                if key not in self.variables:
                    raise ValueError(f"original ride absent from bound: {key}")
                values[key] += n
                if self.journey_encoding == "time_moments":
                    trip = next(t for t in plan.trips if t.cabin_id == r.cabin_id)
                    values[("t", *key[1:])] += n * trip.switch_ticks[i] / 1e6
                    values[("u", *key[1:])] += (
                        n * (trip.switch_ticks[i] + trip.wait_ticks[i]) / 1e6
                    )
        self.model.update()
        by_index = {v.index: values[k] for k, v in self.variables.items()}
        for k, v in self.variables.items():
            if not v.LB - tolerance <= values[k] <= v.UB + tolerance:
                raise ValueError(f"projected variable outside bounds: {k}")
        maximum_violation = 0
        for row in self.model.getConstrs():
            expr = self.model.getRow(row)
            lhs = sum(
                expr.getCoeff(i) * by_index[expr.getVar(i).index]
                for i in range(expr.size())
            )
            violation = (
                abs(lhs - row.RHS)
                if row.Sense == "="
                else lhs - row.RHS
                if row.Sense == "<"
                else row.RHS - lhs
            )
            maximum_violation = max(maximum_violation, violation)
            if violation > tolerance:
                raise ValueError(f"projection violates {row.ConstrName}: {violation}")
        objective = self.model.ObjCon + sum(
            v.Obj * values[k] for k, v in self.variables.items()
        )
        original_value = (metrics.unserved if self.objective == "unserved"
                          else metrics.journey_time_tick / 1e6)
        if objective > original_value + tolerance:
            raise ValueError("projected cost is not optimistic")
        return {
            "projected_cost": objective,
            "original_cost": original_value,
            "rows_checked": self.model.NumConstrs,
            "maximum_violation": maximum_violation,
        }


class ReservoirArrivalBoundBuilder:
    def build(
        self,
        prepared,
        profile="resource_windows",
        *,
        deadline=None,
        max_variables=50000,
        max_rows=250000,
        output=False,
        journey_encoding="legacy",
        objective="journey_time",
        additional_resource_windows=(),
    ):
        if profile not in PROFILES:
            raise ValueError("unknown reservoir bound profile")
        if journey_encoding not in ("legacy", "ride_bounds", "time_moments"):
            raise ValueError("unknown journey encoding")
        if objective not in ("journey_time", "unserved"):
            raise ValueError("unknown reservoir bound objective")
        capacity_objective = objective == "unserved"
        if capacity_objective and journey_encoding != "legacy":
            raise ValueError("capacity bound has no journey-time products or moments")
        started = perf_counter()
        p, part = prepared.problem, prepared.partition
        # Reject unsupported magnitudes before handing integer-derived data to
        # a double-valued LP engine. This is not a tolerance-based time rounding.
        horizon = p.resolved_core.operational_end_tick
        margin = max(
            (
                o.duration_tick
                + tick(p.waiting_policy.maximum_wait_seconds(o.station_id))
                + max(
                    (
                        u.leader_clear_offset_tick
                        + u.separation_after_tick(
                            p.resolved_core.resources_by_id[
                                u.resource_id
                            ].minimum_headway_tick
                        )
                        for u in o.resource_usages
                    ),
                    default=0,
                )
                for o in p.resolved_core.route_options
            ),
            default=0,
        )
        counts = sum(g.count for g in p.demand_groups)
        if (
            max(
                horizon + margin,
                counts,
                p.available_fleet_count * p.cabin_capacity,
                max(counts, p.available_fleet_count * p.cabin_capacity)
                * (horizon + margin),
            )
            >= 2**53
        ):
            raise ValueError(
                "bound coefficients exceed supported exact integer input range"
            )
        options = {o.id: o for o in p.resolved_core.route_options}
        m = gp.Model("reservoir_arrival_bound")
        m.Params.OutputFlag = int(output)
        variables, families = {}, defaultdict(int)
        variable_families = defaultdict(int)

        def variable(key, upper):
            check_deadline(deadline)
            if max_variables is not None and len(variables) >= max_variables:
                raise BoundSizeLimit(
                    f"bound requires more than {max_variables} variables; domain not truncated",
                    variable_families=dict(variable_families),
                    row_families=dict(families),
                )
            v = m.addVar(lb=0, ub=upper, name=str(key))
            variables[key] = v
            variable_families[key[0]] += 1
            return v

        def row(expression, family):
            check_deadline(deadline)
            if max_rows is not None and sum(families.values()) >= max_rows:
                raise BoundSizeLimit(
                    f"bound requires more than {max_rows} rows",
                    variable_families=dict(variable_families),
                    row_families=dict(families),
                )
            families[family] += 1
            m.addConstr(expression, name=f"{family}[{families[family]}]")

        try:
            constant = sum(
                g.count
                * (
                    p.resolved_core.passenger_service_end_tick
                    - tick(g.release_time_seconds)
                )
                / 1e6
                for g in p.demand_groups
            )
            objective = gp.LinExpr(counts if capacity_objective else constant)
            if profile == "arrival_only":
                for g in p.demand_groups:
                    # This control has no cross-group resource competition.
                    from dataclasses import replace

                    lb = analytical_bound(replace(p, demand_groups=(g,))) / max(
                        1, g.count
                    )
                    variable(("served", g.id), g.count)
                    objective += (-1 if capacity_objective else (
                        lb
                        - (
                            p.resolved_core.passenger_service_end_tick
                            - tick(g.release_time_seconds)
                        )
                        / 1e6
                    )) * variables["served", g.id]
            else:
                incoming, outgoing = defaultdict(list), defaultdict(list)
                by_visit = defaultdict(list)
                for a in prepared.arcs:
                    x = variable(("x", a.id), p.available_fleet_count)
                    outgoing[a.visit, a.source].append(x)
                    incoming[a.visit + 1, a.target].append(x)
                    by_visit[a.visit].append(a)
                for node in prepared.dispatch_nodes:
                    incoming[node].append(
                        variable(("dispatch", *node), p.available_fleet_count)
                    )
                for node in prepared.return_nodes:
                    outgoing[node].append(
                        variable(("return", *node), p.available_fleet_count)
                    )
                for node in incoming.keys() | outgoing.keys():
                    row(
                        gp.quicksum(incoming[node]) == gp.quicksum(outgoing[node]),
                        "movement",
                    )
                row(
                    gp.quicksum(v for k, v in variables.items() if k[0] == "dispatch")
                    <= p.available_fleet_count,
                    "fleet",
                )
                loads, alights = defaultdict(list), defaultdict(list)
                ride_groups = {
                    (r.demand_group_id, r.board_visit_index, r.alight_visit_index)
                    for r in p.passenger_build.ride_candidates
                }
                groups = {g.id: g for g in p.demand_groups}
                boarding = defaultdict(list)
                for gid, board, alight in sorted(ride_groups):
                    check_deadline(deadline)
                    g = groups[gid]
                    inc, out = defaultdict(list), defaultdict(list)
                    inc_time, out_time = defaultdict(list), defaultdict(list)
                    # Every original ride starts and ends on STOP; intervening
                    # route durations may optimistically choose STOP or SKIP.
                    state_options = p.resolved_core.route_options_by_state_id
                    origin = next(
                        o
                        for o in state_options[p.visit_states[board]]
                        if o.decision is DddRouteDecision.STOP
                    )
                    destination = next(
                        o
                        for o in state_options[p.visit_states[alight]]
                        if o.decision is DddRouteDecision.STOP
                    )
                    minimum_journey = origin.duration_tick - tick(
                        origin.platform_exit_offset_seconds
                    )
                    minimum_journey += sum(
                        min(o.duration_tick for o in state_options[p.visit_states[j]])
                        for j in range(board + 1, alight)
                    )
                    minimum_journey += tick(destination.platform_entry_offset_seconds)
                    support = []
                    for i in range(board, alight + 1):
                        for a in by_visit[i]:
                            o = options[a.option_id]
                            if (
                                i in (board, alight)
                                and o.decision is not DddRouteDecision.STOP
                            ):
                                continue
                            if i == board and max(u for t, u in a.vertices) + tick(
                                o.platform_exit_offset_seconds
                            ) < tick(g.release_time_seconds):
                                continue
                            earliest_arrival = min(t for t, u in a.vertices) + (
                                tick(o.platform_entry_offset_seconds)
                                if i == alight
                                else 0
                            )
                            if (
                                i == alight
                                and earliest_arrival
                                > p.resolved_core.passenger_service_end_tick
                            ):
                                continue
                            support.append(a)
                    forward, backward = set(), set()
                    for a in support:
                        if a.visit == board or (a.visit, a.source) in forward:
                            forward.add((a.visit + 1, a.target))
                    for a in reversed(support):
                        if a.visit == alight or (a.visit + 1, a.target) in backward:
                            backward.add((a.visit, a.source))
                    for a in support:
                        i = a.visit
                        if (i != board and (i, a.source) not in forward) or (
                            i != alight and (i + 1, a.target) not in backward
                        ):
                            continue
                        o = options[a.option_id]
                        earliest_arrival = min(t for t, u in a.vertices) + (
                            tick(o.platform_entry_offset_seconds) if i == alight else 0
                        )
                        f = variable(
                            ("f", gid, board, a.id),
                            min(g.count, p.cabin_capacity * p.available_fleet_count),
                        )
                        if journey_encoding == "time_moments":
                            # First moments of passenger mass in seconds. These
                            # are continuous linear quantities, not time*flow products.
                            quantity = min(
                                g.count, p.cabin_capacity * p.available_fleet_count
                            )
                            ts = [t / 1e6 for t, u in a.vertices]
                            us = [u / 1e6 for t, u in a.vertices]
                            ws = [(u - t) / 1e6 for t, u in a.vertices]
                            tv = variable(("t", gid, board, a.id), quantity * max(ts))
                            uv = variable(("u", gid, board, a.id), quantity * max(us))
                            for lhs, low, high in (
                                (tv, min(ts), max(ts)),
                                (uv, min(us), max(us)),
                                (uv - tv, min(ws), max(ws)),
                            ):
                                row(lhs >= low * f, "passenger_time_domain")
                                row(lhs <= high * f, "passenger_time_domain")
                            if i == board:
                                row(
                                    uv + origin.platform_exit_offset_seconds * f
                                    >= g.release_time_seconds * f,
                                    "release_time",
                                )
                            else:
                                out_time[i, a.source].append(tv)
                            if i < alight:
                                inc_time[i + 1, a.target].append(
                                    uv + o.duration_tick / 1e6 * f
                                )
                            else:
                                arrival = tv + o.platform_entry_offset_seconds * f
                                row(
                                    arrival
                                    <= p.resolved_core.passenger_service_end_tick
                                    / 1e6
                                    * f,
                                    "arrival_horizon",
                                )
                                row(
                                    arrival
                                    >= (g.release_time_seconds + minimum_journey / 1e6)
                                    * f,
                                    "minimum_journey",
                                )
                        if i == board:
                            boarding[gid].append(f)
                        else:
                            out[i, a.source].append(f)
                        if i < alight:
                            inc[i + 1, a.target].append(f)
                            loads[a.id].append(f)
                        else:
                            alights[a.id].append(f)
                            credited = max(
                                tick(g.release_time_seconds),
                                part.floor(earliest_arrival),
                            )
                            if journey_encoding == "ride_bounds":
                                credited = max(
                                    credited,
                                    tick(g.release_time_seconds) + minimum_journey,
                                )
                            if capacity_objective:
                                objective -= f
                            elif journey_encoding == "time_moments":
                                objective += (
                                    arrival
                                    - p.resolved_core.passenger_service_end_tick
                                    / 1e6
                                    * f
                                )
                            else:
                                objective += (
                                    (
                                        credited
                                        - p.resolved_core.passenger_service_end_tick
                                    )
                                    / 1e6
                                ) * f
                    for node in inc.keys() | out.keys():
                        row(
                            gp.quicksum(inc[node]) == gp.quicksum(out[node]),
                            "passenger_flow",
                        )
                    for node in inc_time.keys() | out_time.keys():
                        row(
                            gp.quicksum(inc_time[node]) == gp.quicksum(out_time[node]),
                            "passenger_time_conservation",
                        )
                for gid, g in groups.items():
                    row(gp.quicksum(boarding[gid]) <= g.count, "demand")
                for family, mapping in [
                    ("capacity", loads),
                    ("alight_capacity", alights),
                ]:
                    for aid, flows in mapping.items():
                        row(
                            gp.quicksum(flows)
                            <= p.cabin_capacity * variables["x", aid],
                            family,
                        )
                if profile == "resource_windows":
                    # Adjacent windows and prefixes include inter-cell competition.
                    tail = p.resolved_core.operational_end_tick + max(
                        (
                            u.leader_clear_offset_tick
                            + u.separation_after_tick(r.minimum_headway_tick)
                            + tick(p.waiting_policy.maximum_wait_seconds(o.station_id))
                            for o in options.values()
                            for u in o.resource_usages
                            for r in p.resolved_core.resources
                            if r.id == u.resource_id
                        ),
                        default=1,
                    )
                    boundaries = sorted(set(part.points) | {tail})
                    windows = sorted(
                        set(zip(boundaries, boundaries[1:]))
                        | {(0, b) for b in boundaries if b > 0}
                        | set(additional_resource_windows)
                    )
                    for r in p.resolved_core.resources:
                        relevant = [
                            (a, u)
                            for a in prepared.arcs
                            for u in options[a.option_id].resource_usages
                            if u.resource_id == r.id
                        ]
                        for left, right in windows:
                            check_deadline(deadline)
                            terms = []
                            for a, u in relevant:
                                # If presence is not certain, zero is the safe coefficient.
                                max_enter = max(
                                    (v if u.follower_enter_wait_coefficient else t)
                                    + u.follower_enter_offset_tick
                                    for t, v in a.vertices
                                )
                                if max_enter > p.resolved_core.operational_end_tick:
                                    continue
                                coefficient = minimum_overlap(a, u, r, left, right)
                                if coefficient:
                                    terms.append((coefficient if capacity_objective else coefficient / 1e6)
                                                 * variables["x", a.id])
                            if terms:
                                row(
                                    gp.quicksum(terms) <= (right - left if capacity_objective else (right - left) / 1e6),
                                    "resource_window",
                                )
            m.setObjective(objective)
            m.update()
            identity = stable_fingerprint(
                {
                    "version": "reservoir_arrival_bound_v1",
                    "domain": p.fingerprint,
                    "profile": profile,
                    "partition": part.points,
                    "journey_encoding": journey_encoding,
                    "objective": "unserved" if capacity_objective else "journey_time",
                    "additional_resource_windows": list(additional_resource_windows),
                }
            )
            return ReservoirArrivalBoundModel(
                prepared,
                m,
                variables,
                profile,
                dict(families),
                perf_counter() - started,
                identity,
                journey_encoding,
                "unserved" if capacity_objective else "journey_time",
            )
        except BaseException:
            m.dispose()
            raise


class ReservoirArrivalBoundOptimizer:
    def solve(self, built, *, deadline, threads=12, events=None, method=-1):
        if built.objective != "journey_time":
            raise ValueError("capacity bounds require the scoped capacity optimizer")
        m = built.model
        if perf_counter() >= deadline:
            raise TimeoutError("deadline reached before LP optimization")
        m.Params.Threads = threads
        m.Params.Method = method
        m.Params.TimeLimit = max(0.001, deadline - perf_counter())
        m.Params.MIPFocus = 0
        m.Params.SoftMemLimit = 4
        start = perf_counter()
        # A partial primal LP objective is NOT a valid lower bound. Export the
        # LP value only after optimality; otherwise retain the analytical bound.
        m.optimize()
        exact_lp = m.Status == GRB.OPTIMAL
        raw = m.ObjVal if exact_lp else None
        lower = max(
            analytical_bound(built.prepared.problem), raw if raw is not None else 0
        )
        bound = GlobalReservoirBound(
            built.prepared.problem.fingerprint,
            lower,
            built.fingerprint,
            "optimal_lp" if exact_lp else "analytical_only",
        )
        result = dict(
            status=int(m.Status),
            raw_lp_bound=raw,
            certified_lower_bound=lower,
            analytical_lower_bound=analytical_bound(built.prepared.problem),
            solve_seconds=perf_counter() - start,
            build_seconds=built.build_seconds,
            variables=m.NumVars,
            rows=m.NumConstrs,
            nonzeros=m.NumNZs,
            row_families=built.row_families,
            model_fingerprint=built.fingerprint,
            objective_scope="single_use_reservoir_global",
            profile=built.profile,
            journey_encoding=built.journey_encoding,
            lp_method=method,
            original_problem_optimal=False,
        )
        if raw is not None and not math.isfinite(raw):
            raise ValueError("nonfinite LP result")
        if events:
            events(result)
        return bound, result
