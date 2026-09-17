"""One physical model, translated to native Z3 arithmetic or Hexaly lists.

The preparation contains domain objects only.  Certificates are checked against
the original problem, not this preparation. No candidate pruning is performed.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any

from ..cp_sat_certificate import stable_fingerprint, validate_ddd_cp_sat_domain
from ..cp_sat_movement import _deterministic_visit_structure
from ..models import DddRouteDecision
from ..reservoir_cp_sat_problem import DddReservoirCpSatProblem
from ..route_topology import unique_stop_route_option
from ..time_ticks import ddd_seconds_to_tick as tick

MODEL_SOURCE_HASH = sha256(Path(__file__).read_bytes()).hexdigest()


@dataclass(frozen=True)
class PreparedNativeStructure:
    operation: str
    movement: Any
    waiting: Any
    states: tuple
    groups: tuple
    rides: tuple
    capacity: int
    boundaries: tuple
    completion: int
    step: int
    manifest_json: str
    domain_fingerprint: str
    bounds: Any = None

    @property
    def fingerprint(self):
        return stable_fingerprint(
            {
                "version": "native_event_structure_v1",
                "domain": self.domain_fingerprint,
                "states": self.states,
                "rides": [q.id for q in self.rides],
                "completion": self.completion,
                "step": self.step,
                "bounds": None if self.bounds is None else self.bounds.manifest,
            }
        )


def prepare_native_structure(problem):
    reservoir = isinstance(problem, DddReservoirCpSatProblem)
    if reservoir:
        problem.validate()
        if problem.boundary_policy is not None:
            raise ValueError("native alternative solvers do not support shared_rope_headway")
        movement, waiting = problem.movement, problem.waiting_policy
        states = tuple(
            (k, problem.visit_states) for k in range(problem.available_fleet_count)
        )
        capacity, boundaries = problem.cabin_capacity, ()
        manifest, fingerprint = problem.manifest, problem.fingerprint
        completion = movement.operational_end_tick
    else:
        manifest = validate_ddd_cp_sat_domain(problem)
        fingerprint = stable_fingerprint(manifest)
        trajectory = problem.resolved_trajectory_problem
        movement, waiting = (
            trajectory.structural_movement_problem,
            trajectory.waiting_policy,
        )
        states = tuple(
            (
                s.cabin_id,
                _deterministic_visit_structure(movement, s.state_id, s.max_visit_count)[
                    0
                ],
            )
            for s in sorted(movement.starts, key=lambda s: s.cabin_id)
        )
        capacity = problem.artifact.config.cabin_capacity
        boundaries = tuple(problem.boundary_context.resource_occurrences)
        completion = movement.operational_end_tick + max(
            o.duration_tick + tick(waiting.maximum_wait_seconds(o.station_id))
            for o in movement.route_options
        )
    passengers = problem.passenger_build
    from ..cp_formulation import prepare_cp_structure

    bounds = prepare_cp_structure(
        movement, passengers, dict(states), reservoir=problem if reservoir else None
    )
    # Keep every integer calculation exact also in double-valued engine reports.
    magnitude = sum(g.count for g in passengers.demand_groups) * (
        completion
        + max(
            tick(o.platform_entry_offset_seconds or 0) for o in movement.route_options
        )
        + movement.passenger_service_end_tick
    )
    if magnitude >= 2**53 or completion >= 2**53:
        raise ValueError("native solver exact reporting range exceeded")
    for option in movement.route_options:
        maximum_wait = tick(waiting.maximum_wait_seconds(option.station_id))
        for usage in option.resource_usages:
            separation = usage.separation_after_tick(
                movement.resources_by_id[usage.resource_id].minimum_headway_tick
            )
            for offset, coefficient in (
                (
                    usage.follower_enter_offset_tick,
                    usage.follower_enter_wait_coefficient,
                ),
                (
                    usage.leader_clear_offset_tick + separation,
                    usage.leader_clear_wait_coefficient,
                ),
            ):
                if any(
                    abs(t + offset + coefficient * w) >= 2**53
                    for t in (0, completion)
                    for w in (0, maximum_wait)
                ):
                    raise ValueError(
                        "native resource time exact reporting range exceeded"
                    )
    return PreparedNativeStructure(
        "reservoir" if reservoir else "fixed_k",
        movement,
        waiting,
        states,
        tuple(passengers.demand_groups),
        tuple(passengers.ride_candidates),
        capacity,
        boundaries,
        completion,
        tick(waiting.step_seconds or 1e-6),
        json.dumps(manifest, sort_keys=True),
        fingerprint,
        bounds,
    )


class Z3Algebra:
    def __init__(self):
        import z3

        self.z = z3
        self.engine = z3.Optimize()
        self.version = z3.get_version_string()
        # z3core deletes its CDLL handle after generating wrappers. In the
        # pinned wheel, d retains the successfully resolved library filename.
        self.engine_path = getattr(z3.z3core, "d", None)
        self.rows = 0

    def integer(self, lo, hi, name):
        x = self.z.Int(name)
        self.add(x >= lo, x <= hi)
        return x

    def boolean(self, name):
        return self.z.Bool(name)

    def bit(self, x):
        return self.z.If(x, 1, 0)

    def ite(self, c, a, b):
        return self.z.If(c, a, b)

    def all(self, *xs):
        return self.z.And(*xs)

    def any(self, *xs):
        return self.z.Or(*xs)

    def implies(self, a, b):
        return self.z.Implies(a, b)

    def add(self, *xs):
        if getattr(self, "fixed_movement", False):
            xs = tuple(self.z.simplify(self.all(x)) for x in xs)
            xs = tuple(x for x in xs if not self.z.is_true(x))
        self.engine.add(*xs)
        self.rows += len(xs)

    def sum(self, xs):
        xs = list(xs)
        value = self.z.Sum(xs) if xs else 0
        return self.z.IntVal(value) if isinstance(value, int) else value

    def resources(self, blocks, deadline):
        pairs = 0
        for intervals in blocks.values():
            if getattr(self, "fixed_movement", False):
                constant_intervals = []
                for presence, start, end in intervals:
                    if self.z.is_false(self.z.simplify(self.all(presence))):
                        continue

                    def number(x):
                        return x if isinstance(x, int) else self.z.simplify(x).as_long()

                    constant_intervals.append((number(start), number(end)))
                latest = None
                for start, end in sorted(constant_intervals):
                    if latest is not None and start < latest:
                        self.add(False)
                    latest = end if latest is None else max(end, latest)
                continue
            for i, (p, start, end) in enumerate(intervals):
                check_deadline(deadline)
                for q, other_start, other_end in intervals[:i]:
                    if pairs % 1024 == 0:
                        check_deadline(deadline)
                        if getattr(self, "progress", None):
                            self.progress(resource_pairs=pairs, constraints=self.rows)
                    self.add(
                        self.implies(
                            self.all(p, q),
                            self.any(end <= other_start, other_end <= start),
                        )
                    )
                    pairs += 1
        return {"resource_pairs": pairs}


class HexalyAlgebra:
    def __init__(self):
        from importlib.metadata import version

        import hexaly.optimizer as hx

        self.hx = hx
        self.engine = hx.HexalyOptimizer()
        self.m = self.engine.model
        self.version = version("hexaly")
        self.engine_path = hx._loaded_library
        self.rows = 0
        self.orders = {}

    def integer(self, lo, hi, name):
        x = self.m.int(lo, hi)
        x.name = name
        return x

    def boolean(self, name):
        x = self.m.bool()
        x.name = name
        return x

    def bit(self, x):
        return x

    def ite(self, c, a, b):
        return self.m.iif(c, a, b)

    def all(self, *xs):
        return self.m.and_(xs)

    def any(self, *xs):
        return self.m.or_(xs)

    def implies(self, a, b):
        return self.m.or_(self.m.not_(a), b)

    def sum(self, xs):
        return self.m.sum(list(xs))

    def add(self, *xs):
        for x in xs:
            self.m.constraint(x)
        self.rows += len(xs)

    def resources(self, blocks, deadline):
        for resource, intervals in blocks.items():
            check_deadline(deadline)
            if not intervals:
                continue
            order = self.m.list(len(intervals))
            self.orders[resource] = order
            for i, (presence, _, _) in enumerate(intervals):
                self.add(self.m.contains(order, i) == presence)
            starts = self.m.array([start for _, start, _ in intervals])
            ends = self.m.array([end for _, _, end in intervals])
            adjacent = self._adjacent(starts, ends, order)
            self.add(
                self.m.and_(
                    self.m.range(1, self.m.max(1, self.m.count(order))), adjacent
                )
            )
        return {"resource_lists": len(self.orders)}

    def _adjacent(self, starts, ends, order):
        return self.m.lambda_function(
            lambda i: (
                self.m.at(ends, self.m.at(order, i - 1))
                <= self.m.at(starts, self.m.at(order, i))
            )
        )


def check_deadline(deadline):
    if deadline is not None and perf_counter() >= deadline:
        raise TimeoutError("native model build budget exhausted")


@dataclass
class NativeModel:
    prepared: PreparedNativeStructure
    algebra: Any
    variables: dict = field(default_factory=dict)
    resources: dict = field(default_factory=lambda: defaultdict(list))
    visit_intervals: dict = field(default_factory=dict)
    objective: Any = None
    objective_kind: str = "journey_time"
    stats: dict = field(default_factory=dict)
    fixed_values: dict = field(default_factory=dict)

    def integer(self, key, lo, hi):
        if key in self.fixed_values:
            value = self.fixed_values[key]
            if not lo <= value <= hi:
                raise ValueError("fixed decision outside its original domain")
            self.variables[key] = self.algebra.sum([value])
        else:
            self.variables[key] = self.algebra.integer(lo, hi, repr(key))
        return self.variables[key]

    def boolean(self, key):
        self.variables[key] = (
            self.algebra.all(self.fixed_values[key])
            if key in self.fixed_values
            else self.algebra.boolean(repr(key))
        )
        return self.variables[key]

    @property
    def fingerprint(self):
        return stable_fingerprint(
            {
                "structure": self.prepared.fingerprint,
                "backend": type(self.algebra).__name__,
                "version": self.algebra.version,
                "builder_source_hash": MODEL_SOURCE_HASH,
                "encoding": "native_v1",
                "objective": self.objective_kind,
                "fixed_values": sorted(
                    (repr(k), val) for k, val in self.fixed_values.items()
                ),
            }
        )


def build_native_model(
    problem,
    *,
    backend="z3",
    objective="journey_time",
    prepared=None,
    deadline=None,
    fixed_plan=None,
    fix_passengers=False,
    progress=None,
):
    if backend not in ("z3", "hexaly") or objective not in ("journey_time", "unserved"):
        raise ValueError("unsupported native backend/objective")
    p = prepared or prepare_native_structure(problem)
    a = Z3Algebra() if backend == "z3" else HexalyAlgebra()
    a.progress = progress
    b = NativeModel(p, a, objective_kind=objective)
    if fixed_plan is not None:
        from .optimizer import plan_values

        values = plan_values(problem, b, fixed_plan)
        b.fixed_values = {
            k: value
            for k, value in values.items()
            if fix_passengers
            or k[0] not in ("ride", "unserved", "alight", "alight_bit")
        }
        a.fixed_movement = True
    v = b.variables
    H = p.movement.operational_end_tick
    reservoir = p.operation == "reservoir"
    starts = {s.cabin_id: s for s in p.movement.starts}
    visit_bounds = {} if p.bounds is None else p.bounds.visit_map
    for n, occurrence in enumerate(p.boundaries):
        resource = p.movement.resources_by_id[occurrence.resource_id]
        end = tick(
            occurrence.leader_clear_time_seconds
        ) + occurrence.separation_after_tick(resource)
        start = max(0, tick(occurrence.follower_enter_time_seconds))
        if end > start:
            b.resources[occurrence.resource_id].append((True, start, end))
    state_nodes = defaultdict(list)
    previous_cabin = None
    for k, states in p.states:
        check_deadline(deadline)
        ts = [b.integer(("time", k, i), 0, p.completion) for i in range(len(states))]
        active = [b.boolean(("active", k, i)) for i in range(len(states))]
        a.add(active[-1] == False)
        if reservoir:
            first, last = (
                tick(problem.dispatch_start_seconds),
                tick(problem.dispatch_end_seconds),
            )
            step = tick(problem.dispatch_step_seconds)
            dispatch = b.integer(("dispatch", k), 0, (last - first) // step)
            a.add(ts[0] == a.ite(active[0], first + step * dispatch, 0))
            a.add(a.implies(active[0] == False, dispatch == 0))
            if previous_cabin is not None:
                a.add(a.implies(active[0], v["active", previous_cabin, 0]))
                a.add(a.implies(active[0], ts[0] >= v["time", previous_cabin, 0]))
        else:
            a.add(active[0], ts[0] == starts[k].time_tick)
        for i, state in enumerate(states):
            if reservoir:
                presence = active[0] if i == 0 else active[i - 1]
                state_nodes[state].append((presence, ts[i]))
                if i:
                    a.add(a.implies(active[i], active[i - 1]))
                    if state != problem.entry_state_id:
                        a.add(active[i] == active[i - 1])
                    else:
                        a.add(
                            a.implies(
                                a.all(active[i - 1], active[i] == False),
                                ts[i] >= tick(problem.return_start_seconds),
                            )
                        )
            else:
                a.add(active[i] == (ts[i] <= H))
            if i == len(states) - 1:
                continue
            options = p.movement.route_options_by_state_id[state]
            choices = {o.id: b.boolean(("route", k, i, o.id)) for o in options}
            maxima = {
                o.id: (
                    tick(p.waiting.maximum_wait_seconds(o.station_id)) // p.step
                    if o.decision is DddRouteDecision.STOP
                    and o.platform_exit_offset_seconds is not None
                    else 0
                )
                for o in options
            }
            w = b.integer(("wait", k, i), 0, max(maxima.values()))
            if (k, i) in visit_bounds:
                bounds = visit_bounds[k, i]
                a.add(
                    a.implies(
                        active[i],
                        a.all(ts[i] >= bounds.earliest, ts[i] <= bounds.latest),
                    )
                )
                if reservoir:
                    a.add(a.implies(active[i], ts[i] + p.step * w <= bounds.latest))
            a.add(a.sum(a.bit(x) for x in choices.values()) == a.bit(active[i]))
            a.add(w <= a.sum(maxima[o.id] * a.bit(choices[o.id]) for o in options))
            for o in options:
                selected = choices[o.id]
                if maxima[o.id]:
                    a.add(
                        a.implies(
                            a.all(selected, w > 0),
                            ts[i] + tick(o.platform_exit_offset_seconds)
                            >= tick(p.waiting.earliest_wait_time_seconds),
                        )
                    )
                for u in o.resource_usages:
                    r = p.movement.resources_by_id[u.resource_id]
                    start = (
                        ts[i]
                        + u.follower_enter_offset_tick
                        + u.follower_enter_wait_coefficient * p.step * w
                    )
                    end = (
                        ts[i]
                        + u.leader_clear_offset_tick
                        + u.leader_clear_wait_coefficient * p.step * w
                        + u.separation_after_tick(r.minimum_headway_tick)
                    )
                    present = a.all(selected, start <= H)
                    a.add(a.implies(present, end > start))
                    b.resources[u.resource_id].append((present, start, end))
            a.add(
                ts[i + 1]
                == ts[i]
                + a.sum(o.duration_tick * a.bit(choices[o.id]) for o in options)
                + p.step * w
            )
            if backend == "hexaly":
                # A visit interval exposes the native scheduling structure. Its
                # bounds are only read when present; inactive tails use scalars.
                iv = a.m.optional_interval(0, p.completion)
                a.add(a.m.presence(iv) == active[i])
                a.add(a.ite(active[i], a.m.start(iv), ts[i]) == ts[i])
                a.add(a.ite(active[i], a.m.end(iv), ts[i + 1]) == ts[i + 1])
                b.visit_intervals[k, i] = iv
        previous_cabin = k
    for nodes in state_nodes.values():
        if fixed_plan is not None and backend == "z3":
            seen = set()
            for present, time in nodes:
                if a.z.is_false(a.z.simplify(present)):
                    continue
                value = a.z.simplify(time).as_long()
                if value in seen:
                    a.add(False)
                seen.add(value)
            continue
        for i, (present, time) in enumerate(nodes):
            check_deadline(deadline)
            for other, other_time in nodes[:i]:
                a.add(a.implies(a.all(present, other), time != other_time))
    if progress:
        progress(
            phase="resources",
            scalar_variables=len(v),
            constraints=a.rows,
            resource_occurrences=sum(len(x) for x in b.resources.values()),
        )
    b.stats.update(a.resources(b.resources, deadline))
    groups = {g.id: g for g in p.groups}
    boards, alights, stops = {}, {}, {}
    for k, states in p.states:
        for i, state in enumerate(states[:-1]):
            o = unique_stop_route_option(
                p.movement, state, error_context="native passengers"
            )
            boards[k, i] = (
                v["time", k, i]
                + tick(o.platform_exit_offset_seconds)
                + p.step * v["wait", k, i]
            )
            alights[k, i] = v["time", k, i] + tick(o.platform_entry_offset_seconds)
            stops[k, i] = v["route", k, i, o.id]
    by_group, by_alight, onboard = (
        defaultdict(list),
        defaultdict(list),
        defaultdict(list),
    )
    service = p.movement.passenger_service_end_tick
    for q in p.rides:
        check_deadline(deadline)
        count = b.integer(
            ("ride", q.id), 0, min(p.capacity, groups[q.demand_group_id].count)
        )
        board, alight = (
            (q.cabin_id, q.board_visit_index),
            (q.cabin_id, q.alight_visit_index),
        )
        a.add(
            a.implies(
                count > 0,
                a.all(
                    stops[board],
                    stops[alight],
                    boards[board]
                    >= max(0, tick(groups[q.demand_group_id].release_time_seconds)),
                    boards[board] <= service,
                    alights[alight] <= service,
                    alights[alight] >= boards[board],
                ),
            )
        )
        by_group[q.demand_group_id].append(count)
        by_alight[alight].append(count)
        for i in range(q.board_visit_index, q.alight_visit_index):
            onboard[q.cabin_id, i].append(count)
    for g in p.groups:
        u = b.integer(("unserved", g.id), 0, g.count)
        a.add(u + a.sum(by_group[g.id]) == g.count)
    for counts in onboard.values():
        a.add(a.sum(counts) <= p.capacity)
    terms = []
    constant = sum(
        g.count * max(0, service - tick(g.release_time_seconds)) for g in p.groups
    )
    if objective == "journey_time":
        for event, counts in by_alight.items():
            n = b.integer(("alight", *event), 0, p.capacity)
            a.add(n == a.sum(counts))
            if backend == "z3" and fixed_plan is not None:
                # Diagnostic fixed timetables have constant arrival times. This
                # is ordinary linear arithmetic, so no binary product needed.
                product = a.z.simplify(alights[event]).as_long() * n
            elif backend == "z3":
                bits = [
                    b.boolean(("alight_bit", *event, bit))
                    for bit in range(p.capacity.bit_length())
                ]
                a.add(
                    n
                    == a.sum((1 << bit) * a.bit(flag) for bit, flag in enumerate(bits))
                )
                product = a.sum(
                    (1 << bit) * a.ite(flag, alights[event], 0)
                    for bit, flag in enumerate(bits)
                )
            else:
                product = n * alights[event]
            terms.append(product - service * n)
        b.objective = constant + a.sum(terms)
    else:
        b.objective = a.sum(v["unserved", g.id] for g in p.groups)
    a.add(
        b.objective
        >= (
            p.bounds.analytical_lower_bound
            if objective == "journey_time" and p.bounds is not None
            else 0
        )
    )
    if backend == "z3":
        b.handle = a.engine.minimize(b.objective)
    else:
        a.m.minimize(b.objective)
        a.m.close()
    decisions = [key for key in v if key not in b.fixed_values]
    boolean_count = sum(
        key[0] in ("active", "route", "alight_bit") for key in decisions
    )
    b.stats.update(
        variables=len(decisions),
        scalar_terms=len(v),
        boolean_decisions=boolean_count,
        integer_decisions=len(decisions) - boolean_count,
        constraints=a.rows,
        rides=len(p.rides),
        visits=sum(len(states) - 1 for _, states in p.states),
        visit_intervals=len(b.visit_intervals),
        fixed_scalar_values=len(v) - len(decisions),
    )
    return b
