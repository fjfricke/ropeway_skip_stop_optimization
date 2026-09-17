"""Single-cabin insertion with immutable outside movements and shared passengers."""

from collections import defaultdict
from dataclasses import dataclass, replace
from time import perf_counter

from ..cp_sat_certificate import stable_fingerprint
from ..cp_sat_passenger import (
    DddCpSatCostEncoding,
    build_ddd_cp_sat_passenger_assignment,
)
from ..reservoir_arc_flow_problem import DddReservoirOperatingMode
from ..reservoir_boundary import state_protection_tick
from ..reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    validate_reservoir_cp_plan,
)
from ..reservoir_cp_sat_movement import build_reservoir_cp_movement
from ..reservoir_lines.evolution.pattern_waiting import with_pattern_waiting
from ..time_ticks import ddd_seconds_to_tick as tick


@dataclass(frozen=True)
class PreparedInsertion:
    problem: object
    outside: DddReservoirCpPlan
    resources: tuple
    states: tuple
    new_id: int
    fingerprint: str


def pilot_problem(problem, waiting_seconds=60, dispatch_end_seconds=300):
    p = replace(
        problem,
        dispatch_start_seconds=0,
        dispatch_end_seconds=dispatch_end_seconds,
        operating_mode=DddReservoirOperatingMode.SKIP_STOP,
    )
    if waiting_seconds == 0:
        return p
    return with_pattern_waiting(p, waiting_seconds, earliest_seconds=0)


def validate_lifecycle(problem, plan):
    metrics = validate_reservoir_cp_plan(problem, plan)
    cycle = len(problem.cycle_states)
    deadline = problem.resolved_core.passenger_service_end_tick
    for t in plan.trips:
        n = len(t.route_option_ids)
        if (
            n % cycle
            or t.return_tick < deadline
            or (n > cycle and t.switch_ticks[n - cycle] >= deadline)
        ):
            raise ValueError("trip violates first return at/after service deadline")
    return metrics


def prepare_insertion(problem, outside, *, deadline=None):
    validate_lifecycle(problem, outside)
    if len(outside.trips) >= problem.available_fleet_count:
        raise ValueError("fleet exhausted")
    # Labels are canonicalized independently of input IDs and tuple order.
    from ..reservoir_hybrid.repair import translate_plan

    ordered = sorted(outside.trips, key=lambda t: (t.switch_ticks[0], t.cabin_id))
    outside = translate_plan(
        problem, problem, outside, {t.cabin_id: i for i, t in enumerate(ordered)}
    )
    resources, states = defaultdict(list), defaultdict(list)
    options = {o.id: o for o in problem.resolved_core.route_options}
    for t in outside.trips:
        if deadline is not None and perf_counter() >= deadline:
            raise TimeoutError("calendar preparation deadline")
        for oid, start, wait in zip(
            t.route_option_ids, t.switch_ticks, t.wait_ticks, strict=True
        ):
            o = options[oid]
            states[o.from_state_id].append(
                (start, start + state_protection_tick(problem, o.from_state_id))
            )
            for u in o.resource_usages:
                r = problem.resolved_core.resources_by_id[u.resource_id]
                a = (
                    start
                    + u.follower_enter_offset_tick
                    + u.follower_enter_wait_coefficient * wait
                )
                b = (
                    start
                    + u.leader_clear_offset_tick
                    + u.leader_clear_wait_coefficient * wait
                    + u.separation_after_tick(r.minimum_headway_tick)
                )
                if a <= problem.resolved_core.operational_end_tick:
                    resources[r.id].append((a, b))
        states[problem.entry_state_id].append(
            (
                t.return_tick,
                t.return_tick + state_protection_tick(problem, problem.entry_state_id),
            )
        )
    res = tuple((r, tuple(sorted(v))) for r, v in sorted(resources.items()))
    sta = tuple((s, tuple(sorted(v))) for s, v in sorted(states.items()))
    return PreparedInsertion(
        problem,
        outside,
        res,
        sta,
        len(outside.trips),
        stable_fingerprint(
            {
                "version": "greedy_insertion_v1",
                "domain": problem.fingerprint,
                "resources": res,
                "states": sta,
            }
        ),
    )


@dataclass(frozen=True)
class InsertionModel:
    movement: object
    passengers: object
    prepared: PreparedInsertion
    fingerprint: str


def build_insertion(prepared, *, deadline=None, objective="unserved"):
    if objective not in ("unserved", "journey_time"):
        raise ValueError("unknown insertion objective")
    p = prepared.problem
    local = replace(p, available_fleet_count=1)
    b = build_reservoir_cp_movement(
        local, deadline=deadline, dispatch_order_symmetry=False
    )
    m, k = b.model, prepared.new_id
    # Preserve canonical visits while rekeying the sole variable trajectory.
    for attr in ("time_by_cabin", "active_by_cabin", "states_by_cabin"):
        table = getattr(b, attr)
        table[k] = table.pop(0)
    if k:
        old = dict(b.selection_by_key)
        b.selection_by_key.clear()
        b.selection_by_key.update({(k, i, o): v for (_, i, o), v in old.items()})
        old = dict(b.wait_steps_by_key)
        b.wait_steps_by_key.clear()
        b.wait_steps_by_key.update({(k, i): v for (_, i), v in old.items()})
    a, t = b.active_by_cabin[k], b.time_by_cabin[k]
    m.add(a[0] == 1)
    cycle, end = len(p.cycle_states), p.resolved_core.passenger_service_end_tick
    elapsed = 0
    for i, v in enumerate(t):
        # Inactive tails equal the return time, which is >= service end.
        lo = min(elapsed, end)
        v.proto.domain.clear()
        v.proto.domain.extend([lo, p.resolved_core.operational_end_tick])
        if i < len(t) - 1:
            elapsed += min(
                o.duration_tick
                for o in p.movement.route_options_by_state_id[p.visit_states[i]]
            )
    # Tighten affine resource auxiliaries from their defining equalities.
    proto = m.proto
    for c in proto.constraints:
        if (
            c.has_linear()
            and not c.enforcement_literal
            and next(iter(c.linear.domain)) == list(c.linear.domain)[-1]
        ):
            terms = list(zip(c.linear.vars, c.linear.coeffs))
            for index, coef in terms:
                v = proto.variables[index]
                if (
                    not v.name.startswith(
                        ("resource_entry[", "resource_end[", "resource_size[")
                    )
                    or abs(coef) != 1
                ):
                    continue
                lower = upper = next(iter(c.linear.domain))
                for j, cc in terms:
                    if j == index:
                        continue
                    d = list(proto.variables[j].domain)
                    lower -= max(cc * d[0], cc * d[-1])
                    upper -= min(cc * d[0], cc * d[-1])
                lower, upper = (
                    min(coef * lower, coef * upper),
                    max(coef * lower, coef * upper),
                )
                d = list(v.domain)
                lower = max(lower, d[0])
                upper = min(upper, d[-1])
                if lower > upper:
                    raise ValueError("inconsistent safe resource bounds")
                v.domain.clear()
                v.domain.extend([lower, upper])
    for i in range(cycle, len(t), cycle):
        m.add(t[i] >= end).only_enforce_if([a[i - 1], a[i].Not()])
        m.add(t[i] <= end - 1).only_enforce_if(a[i])
    for rid, values in prepared.resources:
        fixed = [
            m.new_fixed_size_interval_var(lo, hi - lo, f"fixed_resource[{rid},{j}]")
            for j, (lo, hi) in enumerate(values)
        ]
        m.add_no_overlap(fixed + b.resource_intervals[rid])
    for state, values in prepared.states:
        fixed = [
            m.new_fixed_size_interval_var(lo, hi - lo, f"fixed_state[{state},{j}]")
            for j, (lo, hi) in enumerate(values)
        ]
        new = []
        for i, s in enumerate(p.visit_states):
            if s == state:
                new.append(
                    m.new_optional_fixed_size_interval_var(
                        t[i],
                        state_protection_tick(p, state),
                        a[0] if i == 0 else a[i - 1],
                        f"new_state[{state},{i}]",
                    )
                )
        m.add_no_overlap(fixed + new)
    # Old events are constants, not movement decisions. Passenger counts stay free.
    for trip in prepared.outside.trips:
        n = len(trip.route_option_ids)
        cid = trip.cabin_id
        b.states_by_cabin[cid] = p.visit_states[: n + 1]
        b.time_by_cabin[cid] = list(trip.switch_ticks) + [trip.return_tick]
        b.active_by_cabin[cid] = [1] * n + [0]
        for i, state in enumerate(p.visit_states[:n]):
            b.wait_steps_by_key[cid, i] = (
                trip.wait_ticks[i] // b.waiting_step_tick if i < n else 0
            )
            for o in p.movement.route_options_by_state_id[state]:
                b.selection_by_key[cid, i, o.id] = m.new_constant(
                    int(i < n and trip.route_option_ids[i] == o.id)
                )
    passenger_build = p.passenger_build
    trips = {t.cabin_id: t for t in prepared.outside.trips}
    options = {o.id: o for o in p.resolved_core.route_options}
    groups = {g.id: g for g in p.demand_groups}

    def possible(q):
        if q.cabin_id == k:
            return True
        tr = trips.get(q.cabin_id)
        if tr is None or q.alight_visit_index >= len(tr.route_option_ids):
            return False
        bo = options[tr.route_option_ids[q.board_visit_index]]
        ao = options[tr.route_option_ids[q.alight_visit_index]]
        if (
            bo.platform_exit_offset_seconds is None
            or ao.platform_entry_offset_seconds is None
        ):
            return False
        board = (
            tr.switch_ticks[q.board_visit_index]
            + tick(bo.platform_exit_offset_seconds)
            + tr.wait_ticks[q.board_visit_index]
        )
        arrival = tr.switch_ticks[q.alight_visit_index] + tick(
            ao.platform_entry_offset_seconds
        )
        return (
            tick(groups[q.demand_group_id].release_time_seconds)
            <= board
            <= arrival
            <= end
        )

    passenger_build = replace(
        passenger_build,
        ride_candidates=tuple(
            q for q in passenger_build.ride_candidates if possible(q)
        ),
    )
    passengers = build_ddd_cp_sat_passenger_assignment(
        p.movement,
        passenger_build,
        p.cabin_capacity,
        b,
        with_journey_cost=objective == "journey_time",
        cost_encoding=DddCpSatCostEncoding.UNARY,
        deadline_monotonic=deadline,
    )
    m.minimize(passengers.objective_expression)
    for rid, count in prepared.outside.ride_counts.items():
        m.add_hint(passengers.ride_count[rid], count)
    if m.validate():
        raise ValueError(m.validate())
    return InsertionModel(
        b,
        passengers,
        prepared,
        stable_fingerprint(
            {
                "prepared": prepared.fingerprint,
                "encoding": "shared_integer_event_model_v1",
                "model": str(m.proto),
            }
        ),
    )
