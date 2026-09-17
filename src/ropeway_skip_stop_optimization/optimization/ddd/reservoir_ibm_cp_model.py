"""Native IBM interval model for the existing single-use reservoir domain.

DOcplex is an optional dependency. No integer tick rounding, trajectory pruning,
state-order fixing, or change of passenger/return semantics is performed here.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from time import perf_counter

from docplex.cp import expression as expr
from docplex.cp.model import CpoModel
from docplex.cp.solution import CpoModelSolution

from .models import DddRouteDecision
from .cp_formulation import DddCpFormulationConfig, prepare_cp_structure, formulation_identity
from .reservoir_cp_sat import DddReservoirCpObjective
from .reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    DddReservoirCpTrip,
    validate_reservoir_cp_plan,
)
from .reservoir_cp_sat_problem import DddReservoirCpSatProblem
from .route_topology import unique_stop_route_option
from .time_ticks import ddd_seconds_to_tick as tick


@dataclass(frozen=True)
class DddReservoirIbmCpModel:
    model: CpoModel
    times: dict
    active: dict
    routes: dict
    waits: dict
    ride_counts: dict
    objective: object
    wait_step: int
    stats: dict
    formulation: DddCpFormulationConfig = field(default_factory=DddCpFormulationConfig)
    interval_specs: tuple = ()
    prepared: object = None

    def extract(
        self, problem: DddReservoirCpSatProblem, solution
    ) -> DddReservoirCpPlan:
        trips = []
        for k in range(problem.available_fleet_count):
            ids, times, waits = [], [], []
            for i, state in enumerate(problem.visit_states[:-1]):
                if not solution.get_value(self.active[k][i]):
                    break
                oid = next(
                    o.id
                    for o in problem.movement.route_options_by_state_id[state]
                    if solution.get_value(self.routes[k, i, o.id])
                )
                ids.append(oid)
                times.append(int(solution.get_value(self.times[k][i])))
                waits.append(int(solution.get_value(self.waits[k, i])) * self.wait_step)
            if ids:
                trips.append(
                    DddReservoirCpTrip(
                        k,
                        tuple(ids),
                        tuple(times),
                        tuple(waits),
                        int(solution.get_value(self.times[k][len(ids)])),
                    )
                )
        return DddReservoirCpPlan(
            tuple(trips),
            {
                q: int(solution.get_value(v))
                for q, v in self.ride_counts.items()
                if solution.get_value(v)
            },
        )

    def set_primal(self, problem, plan, *, fix_movement=False):
        validate_reservoir_cp_plan(problem, plan)
        ordered = sorted(plan.trips, key=lambda t: (t.switch_ticks[0], t.cabin_id))
        if [t.cabin_id for t in ordered] != list(range(len(ordered))):
            raise ValueError("IBM seed requires canonical IDs ordered by dispatch")
        by_cabin = {t.cabin_id: t for t in plan.trips}
        starting = CpoModelSolution()

        def assign(var, value):
            starting.add_integer_var_solution(var, value)
            if fix_movement:
                self.model.add(var == value)

        for k in self.times:
            trip = by_cabin.get(k)
            n = len(trip.route_option_ids) if trip else 0
            for i, state in enumerate(problem.visit_states):
                assign(self.active[k][i], int(i < n))
                assign(
                    self.times[k][i],
                    0
                    if trip is None
                    else trip.switch_ticks[i]
                    if i < n
                    else trip.return_tick,
                )
                if i == len(problem.visit_states) - 1:
                    continue
                assign(
                    self.waits[k, i],
                    0 if i >= n else trip.wait_ticks[i] // self.wait_step,
                )
                for o in problem.movement.route_options_by_state_id[state]:
                    assign(
                        self.routes[k, i, o.id],
                        int(i < n and trip.route_option_ids[i] == o.id),
                    )
        if any(v and q not in self.ride_counts for q,v in plan.ride_counts.items()):
            raise ValueError("positive IBM seed count on pruned ride")
        if self.formulation.enabled("hints"):
            from .ibm_cp_native import add_interval_hints
            add_interval_hints(starting, problem, plan, self.interval_specs)
        for q, v in self.ride_counts.items():
            starting.add_integer_var_solution(v, plan.ride_counts.get(q, 0))
        self.model.set_starting_point(starting)


def build_ddd_reservoir_ibm_cp(
    problem: DddReservoirCpSatProblem,
    *,
    objective=DddReservoirCpObjective.JOURNEY_TIME,
    deadline=None,
    formulation=DddCpFormulationConfig(),
) -> DddReservoirIbmCpModel:
    problem.validate()
    if problem.boundary_policy is not None:
        raise ValueError("IBM CP does not yet support shared_rope_headway; use CP-SAT or phase arc-flow")
    formulation.validate("ibm")
    if not isinstance(objective, DddReservoirCpObjective):
        raise ValueError("invalid IBM reservoir objective")

    def check():
        if deadline is not None and perf_counter() >= deadline:
            raise TimeoutError("IBM reservoir model build budget exhausted")

    check()
    m = CpoModel(name="ropeway_single_use_reservoir")
    core = problem.resolved_core
    horizon = core.operational_end_tick
    service = core.passenger_service_end_tick
    if horizon + 1 > expr.INTERVAL_MAX:
        raise ValueError("IBM interval range cannot represent the original tick domain")
    states = problem.visit_states
    policy = problem.waiting_policy
    step = tick(policy.step_seconds or 1e-6)
    times, active, routes, waits = {}, {}, {}, {}
    resources = {r.id: [] for r in core.resources}
    nodes = {s.id: [] for s in core.states}
    node_vars, interval_specs = {}, []
    native = formulation.movement_encoding == "native_visits"
    preprocessing_started = perf_counter()
    prepared = None if formulation.legacy else prepare_cp_structure(problem.movement, problem.passenger_build, {k:states for k in range(problem.available_fleet_count)}, reservoir=problem)
    preprocessing_seconds = perf_counter() - preprocessing_started
    resource_count = 0
    for k in range(problem.available_fleet_count):
        check()
        times[k] = [m.integer_var(0, horizon, f"t_{k}_{i}") for i in range(len(states))]
        active[k] = [m.binary_var(f"a_{k}_{i}") for i in range(len(states))]
        t, a = times[k], active[k]
        m.add(a[-1] == 0)
        first, last = (
            tick(problem.dispatch_start_seconds),
            tick(problem.dispatch_end_seconds),
        )
        ds = tick(problem.dispatch_step_seconds)
        d = m.integer_var(0, (last - first) // ds, f"d_{k}")
        m.add(m.if_then(a[0] == 1, t[0] == first + ds * d))
        m.add(m.if_then(a[0] == 0, m.logical_and(t[0] == 0, d == 0)))
        if k:
            m.add(a[0] <= active[k - 1][0])
            m.add(m.if_then(a[0] == 1, t[0] >= times[k - 1][0]))
        for i, state in enumerate(states):
            present = a[0] if i == 0 else a[i - 1]
            node = m.interval_var(
                start=(0, horizon),
                end=(1, horizon + 1),
                size=1,
                optional=True,
                name=f"node_{k}_{i}",
            )
            m.add(m.presence_of(node) == present)
            m.add(m.if_then(present == 1, m.start_of(node) == t[i]))
            nodes[state].append(node)
            node_vars[k,i] = node
            interval_specs.append((node,"node",k,i,None,None))
            if i:
                m.add(a[i] <= a[i - 1])
                if state != problem.entry_state_id:
                    m.add(a[i] == a[i - 1])
                else:
                    m.add(
                        m.if_then(
                            a[i - 1] - a[i] == 1,
                            t[i] >= tick(problem.return_start_seconds),
                        )
                    )
            if i == len(states) - 1:
                continue
            options = problem.movement.route_options_by_state_id[state]
            maxima = {
                o.id: tick(policy.maximum_wait_seconds(o.station_id)) // step
                if o.decision is DddRouteDecision.STOP
                else 0
                for o in options
            }
            maximum = max(maxima.values())
            w = m.integer_var(0, maximum, f"w_{k}_{i}")
            waits[k, i] = w
            for o in options:
                routes[k, i, o.id] = m.binary_var(f"r_{k}_{i}_{o.id}")
            m.add(m.sum([routes[k, i, o.id] for o in options]) == a[i])
            m.add(w <= m.sum([maxima[o.id] * routes[k, i, o.id] for o in options]))
            for o in options:
                selected = routes[k, i, o.id]
                if maxima[o.id]:
                    m.add(
                        m.if_then(
                            m.logical_and(w > 0, selected == 1),
                            t[i] + tick(o.platform_exit_offset_seconds)
                            >= tick(policy.earliest_wait_time_seconds),
                        )
                    )
                for ui, usage in enumerate(o.resource_usages):
                    resource = core.resources_by_id[usage.resource_id]
                    headway = usage.separation_after_tick(resource.minimum_headway_tick)
                    enter = (
                        t[i]
                        + usage.follower_enter_offset_tick
                        + usage.follower_enter_wait_coefficient * step * w
                    )
                    end = (
                        t[i]
                        + usage.leader_clear_offset_tick
                        + usage.leader_clear_wait_coefficient * step * w
                        + headway
                    )
                    start_bounds = (
                        min(
                            usage.follower_enter_offset_tick,
                            usage.follower_enter_offset_tick
                            + usage.follower_enter_wait_coefficient * step * maximum,
                        ),
                        horizon
                        + max(
                            usage.follower_enter_offset_tick,
                            usage.follower_enter_offset_tick
                            + usage.follower_enter_wait_coefficient * step * maximum,
                        ),
                    )
                    end_bounds = (
                        min(
                            usage.leader_clear_offset_tick + headway,
                            usage.leader_clear_offset_tick
                            + headway
                            + usage.leader_clear_wait_coefficient * step * maximum,
                        ),
                        horizon
                        + max(
                            usage.leader_clear_offset_tick + headway,
                            usage.leader_clear_offset_tick
                            + headway
                            + usage.leader_clear_wait_coefficient * step * maximum,
                        ),
                    )
                    base = (
                        usage.leader_clear_offset_tick
                        + headway
                        - usage.follower_enter_offset_tick
                    )
                    extra = (
                        (
                            usage.leader_clear_wait_coefficient
                            - usage.follower_enter_wait_coefficient
                        )
                        * step
                        * maximum
                    )
                    sizes = (min(base, base + extra), max(base, base + extra))
                    if (
                        sizes[0] <= 0
                        or min(*start_bounds, *end_bounds) < expr.INTERVAL_MIN
                        or max(*start_bounds, *end_bounds, *sizes) > expr.INTERVAL_MAX
                    ):
                        raise ValueError(
                            "IBM cannot represent original resource interval domain"
                        )
                    iv = m.interval_var(
                        start=start_bounds,
                        end=end_bounds,
                        size=sizes,
                        optional=True,
                        name=f"res_{k}_{i}_{o.id}_{ui}",
                    )
                    presence = m.logical_and(selected == 1, enter <= horizon)
                    m.add(m.presence_of(iv) == presence)
                    m.add(
                        m.if_then(
                            m.presence_of(iv),
                            m.logical_and(m.start_of(iv) == enter, m.end_of(iv) == end),
                        )
                    )
                    resources[resource.id].append(iv)
                    interval_specs.append((iv,"resource",k,i,o,usage))
                    resource_count += 1
            if not native:
                m.add(t[i+1] == t[i] + m.sum([o.duration_tick * routes[k,i,o.id] for o in options]) + step*w)
            else:
                m.add(m.if_then(a[i] == 0, t[i+1] == t[i]))
    if native:
        from .ibm_cp_native import add_native_visits
        add_native_visits(m, problem, node_vars, times, active, routes, waits, step, interval_specs)
    if formulation.enabled("temporal"):
        for v in prepared.visits:
            a,t,w = active[v.cabin_id][v.visit_index], times[v.cabin_id][v.visit_index], waits[v.cabin_id,v.visit_index]
            if v.earliest > v.latest:
                m.add(a == 0)
            else:
                m.add(m.if_then(a == 1, m.logical_and(t >= v.earliest, t + step*w <= v.latest)))
    for values in (*resources.values(), *nodes.values()):
        m.add(m.no_overlap(values))
    check()
    groups = {g.id: g for g in problem.demand_groups}
    stops = {
        s: unique_stop_route_option(problem.movement, s, error_context="IBM reservoir")
        for s in problem.cycle_states
    }
    by_group, by_alight, onboard = (
        defaultdict(list),
        defaultdict(list),
        defaultdict(list),
    )
    quantities = {}
    boarding = defaultdict(list)
    bounds = {} if prepared is None else prepared.ride_map
    alight_candidates = defaultdict(list)
    for index, q in enumerate(problem.passenger_build.ride_candidates):
        if index % 256 == 0:
            check()
        if formulation.enabled("temporal") and bounds[q.id].exclusion:
            continue
        g, k, b, a = (
            groups[q.demand_group_id],
            q.cabin_id,
            q.board_visit_index,
            q.alight_visit_index,
        )
        bo, ao = stops[states[b]], stops[states[a]]
        quantity = m.integer_var(0, min(problem.cabin_capacity, g.count), f"q_{index}")
        quantities[q.id] = quantity
        departure = (
            times[k][b] + tick(bo.platform_exit_offset_seconds) + step * waits[k, b]
        )
        arrival = times[k][a] + tick(ao.platform_entry_offset_seconds)
        m.add(
            m.if_then(
                quantity > 0,
                m.logical_and(
                    [
                        routes[k, b, bo.id] == 1,
                        routes[k, a, ao.id] == 1,
                        departure >= tick(g.release_time_seconds),
                        departure <= service,
                        arrival <= service,
                        arrival >= departure,
                    ]
                ),
            )
        )
        by_group[g.id].append(quantity)
        by_alight[k, a].append(quantity)
        boarding[k,b].append(quantity)
        alight_candidates[k,a].append(q)
        for i in range(b, a):
            onboard[k, i].append(quantity)
    if formulation.enabled("passenger_links"):
        for collection in (boarding, by_alight):
            for (k,i),values in collection.items():
                m.add(m.sum(values) <= problem.cabin_capacity * routes[k,i,stops[states[i]].id])
        for (k,i),values in onboard.items():
            m.add(m.sum(values) <= problem.cabin_capacity * active[k][i])
    unserved = {}
    for g in groups.values():
        u = m.integer_var(0, g.count, f"unserved_{g.id}")
        m.add(m.sum(by_group[g.id]) + u == g.count)
        unserved[g.id] = u
    for values in onboard.values():
        m.add(m.sum(values) <= problem.cabin_capacity)
    constant = sum(
        g.count * (service - tick(g.release_time_seconds)) for g in groups.values()
    )
    magnitude = constant
    terms = []
    for (k, i), values in sorted(by_alight.items()):
        n = m.integer_var(0, problem.cabin_capacity, f"alight_count_{k}_{i}")
        m.add(n == m.sum(values))
        arrival = times[k][i] + tick(stops[states[i]].platform_entry_offset_seconds)
        magnitude += problem.cabin_capacity * (
            horizon + tick(stops[states[i]].platform_entry_offset_seconds) + service
        )
        if objective is DddReservoirCpObjective.JOURNEY_TIME:
            product = n * arrival
            terms.append(product - service * n)
            if formulation.enabled("journey_bounds"):
                m.add(product >= m.sum([bounds[q.id].minimum_arrival*quantities[q.id] for q in alight_candidates[k,i]]))
    if magnitude >= min(2**53, expr.INT_MAX):
        raise ValueError("IBM objective exceeds supported exact integer range")
    cost = (
        constant + m.sum(terms)
        if objective is DddReservoirCpObjective.JOURNEY_TIME
        else m.sum(list(unserved.values()))
    )
    if objective is DddReservoirCpObjective.JOURNEY_TIME and formulation.enabled("journey_bounds"):
        total = m.integer_var(prepared.analytical_lower_bound, constant, "bounded_journey_cost")
        m.add(total == cost)
        m.add(total >= m.sum([(service-tick(g.release_time_seconds))*unserved[g.id] for g in groups.values()]) + m.sum([bounds[q].minimum_journey*v for q,v in quantities.items()]))
        cost = total
    m.add(m.minimize(cost))
    s = m.get_statistics()
    stats = dict(
        variables=s.nb_integer_vars + s.nb_interval_vars,
        integer_variables=s.nb_integer_vars,
        interval_variables=s.nb_interval_vars,
        constraints=s.nb_constraints,
        resource_intervals=resource_count,
        ride_candidates=len(quantities),
        visits_per_cabin=len(states) - 1,
        available_cabins=problem.available_fleet_count,
    )
    stats["preprocessing_seconds"] = preprocessing_seconds
    if not formulation.legacy:
        stats["preprocessing"] = formulation_identity(formulation, prepared)
    return DddReservoirIbmCpModel(
        m, times, active, routes, waits, quantities, cost, step, stats, formulation, tuple(interval_specs), prepared
    )
