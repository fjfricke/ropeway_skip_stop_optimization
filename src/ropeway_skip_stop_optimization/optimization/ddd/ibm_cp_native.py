"""IBM-native visit alternatives and complete interval starting points."""

from .time_ticks import ddd_seconds_to_tick as tick


def add_native_visits(m, problem, nodes, times, active, routes, waits, step, specs):
    horizon = problem.resolved_core.operational_end_tick
    modes = {}
    for k in times:
        for i, state in enumerate(problem.visit_states[:-1]):
            parent = m.interval_var(
                start=(0, horizon),
                end=(0, horizon),
                optional=True,
                name=f"visit_{k}_{i}",
            )
            m.add(m.presence_of(parent) == active[k][i])
            children = []
            for o in problem.movement.route_options_by_state_id[state]:
                maximum = (
                    tick(problem.waiting_policy.maximum_wait_seconds(o.station_id))
                    if o.decision.value == "stop"
                    else 0
                )
                child = m.interval_var(
                    start=(0, horizon),
                    end=(0, horizon),
                    size=(o.duration_tick, o.duration_tick + maximum),
                    optional=True,
                    name=f"mode_{k}_{i}_{o.id}",
                )
                m.add(m.presence_of(child) == routes[k, i, o.id])
                m.add(
                    m.if_then(
                        m.presence_of(child),
                        m.size_of(child) == o.duration_tick + step * waits[k, i],
                    )
                )
                modes[k, i, o.id] = child
                children.append(child)
                specs.append((child, "mode", k, i, o, None))
            m.add(m.alternative(parent, children))
            m.add(m.start_at_start(parent, nodes[k, i]))
            m.add(m.end_at_start(parent, nodes[k, i + 1]))
            specs.append((parent, "visit", k, i, None, None))
    for iv, kind, k, i, o, u in specs:
        if kind != "resource":
            continue
        mode = modes[k, i, o.id]
        headway = u.separation_after_tick(
            problem.resolved_core.resources_by_id[u.resource_id].minimum_headway_tick
        )
        if u.follower_enter_wait_coefficient == 0:
            m.add(m.start_at_start(mode, iv, u.follower_enter_offset_tick))
        elif u.follower_enter_wait_coefficient == 1:
            m.add(
                m.end_at_start(mode, iv, u.follower_enter_offset_tick - o.duration_tick)
            )
        if u.leader_clear_wait_coefficient == 0:
            m.add(m.start_at_end(mode, iv, u.leader_clear_offset_tick + headway))
        elif u.leader_clear_wait_coefficient == 1:
            m.add(
                m.end_at_end(
                    mode, iv, u.leader_clear_offset_tick + headway - o.duration_tick
                )
            )


def add_interval_hints(starting, problem, plan, specs):
    trips = {t.cabin_id: t for t in plan.trips}
    for iv, kind, k, i, o, u in specs:
        trip = trips.get(k)
        n = len(trip.route_option_ids) if trip else 0
        present = (n > 0 and i <= n) if kind == "node" else i < n
        if present and kind in ("mode", "resource"):
            present = trip.route_option_ids[i] == o.id
        if present:
            t = trip.switch_ticks[i] if i < n else trip.return_tick
            if kind == "node":
                start, end = t, t + 1
            elif kind == "resource":
                w = trip.wait_ticks[i]
                headway = u.separation_after_tick(
                    problem.resolved_core.resources_by_id[
                        u.resource_id
                    ].minimum_headway_tick
                )
                start = (
                    t
                    + u.follower_enter_offset_tick
                    + u.follower_enter_wait_coefficient * w
                )
                end = (
                    t
                    + u.leader_clear_offset_tick
                    + u.leader_clear_wait_coefficient * w
                    + headway
                )
                present = start <= problem.resolved_core.operational_end_tick
            else:
                start = t
                end = trip.switch_ticks[i + 1] if i + 1 < n else trip.return_tick
        if present:
            starting.add_interval_var_solution(
                iv, presence=True, start=start, end=end, size=end - start
            )
        else:
            starting.add_interval_var_solution(iv, presence=False)
