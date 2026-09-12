"""Native DyPDL event construction; no scheduling decisions in solver callbacks."""

from dataclasses import dataclass
from .structure import PreparedDidpStructure
from ..time_ticks import ddd_seconds_to_tick as tick


@dataclass
class BuiltDidpModel:
    prepared: PreparedDidpStructure
    model: object
    variables: dict
    transitions: dict
    metadata: dict


def build_didp_model(p: PreparedDidpStructure) -> BuiltDidpModel:
    import didppy as dp

    if dp.__version__ != "0.10.1":
        raise RuntimeError("The DIDP pilot requires didppy==0.10.1")
    m = dp.Model(maximize=True, float_cost=False)
    v = {}

    def integer(name, target=0):
        result = m.add_int_var(target=target, name=name)
        v[name] = result
        return result

    def floating(name, target=0):
        result = m.add_float_var(target=float(target), name=name)
        v[name] = result
        return result

    times = [floating(f"time/{k}", s.time_tick) for k, s in enumerate(p.starts)]
    visits = [integer(f"visit/{k}") for k in range(len(p.starts))]
    remaining = [
        integer(f"remaining/{g}", group.count) for g, group in enumerate(p.groups)
    ]
    due = [
        [integer(f"due/{k}/{j}") for j in range(s.max_visit_count)]
        for k, s in enumerate(p.starts)
    ]
    phase, operation, cursor = (
        integer("phase"),
        integer("operation", -1),
        integer("cursor"),
    )
    load, lo, hi = integer("load"), integer("lo"), integer("hi")
    pending_resource = integer("pending_resource", -1)
    pending_entry, pending_end = floating("pending_entry"), floating("pending_end")
    resume_phase, resume_cursor = integer("resume_phase"), integer("resume_cursor")
    required = floating("required")
    latest_board, latest_next = (
        floating("latest_board", p.sentinel),
        floating("latest_next", p.sentinel),
    )
    calendars = []
    for r, size in enumerate(p.calendar_sizes):
        calendars.append(
            (
                integer(f"count/{r}"),
                [floating(f"entry/{r}/{j}", p.sentinel) for j in range(size)],
                [floating(f"end/{r}/{j}", p.sentinel) for j in range(size)],
            )
        )
    transitions, metadata = {}, {}

    def add(name, conditions, effects, gain=0, forced=False, info=None):
        tr = dp.Transition(
            name=name,
            cost=gain + dp.IntExpr.state_cost(),
            preconditions=conditions,
            effects=effects,
        )
        m.add_transition(tr, forced=forced)
        transitions[name] = tr
        metadata[name] = info

    now = times[0]
    for time in times[1:]:
        now = dp.min(now, time)
    for r, (count, entries, ends) in enumerate(calendars):
        if not entries:
            continue
        effects = [(count, count - 1)]
        for j in range(len(entries)):
            effects.extend(
                [
                    (
                        entries[j],
                        entries[j + 1] if j + 1 < len(entries) else float(p.sentinel),
                    ),
                    (ends[j], ends[j + 1] if j + 1 < len(ends) else float(p.sentinel)),
                ]
            )
        add(
            f"expire/{r}", [phase == 0, count > 0, ends[0] <= now], effects, forced=True
        )
    group_index = {g.id: i for i, g in enumerate(p.groups)}
    resource_index = {r.id: i for i, r in enumerate(p.resources)}
    for op in p.operations:
        k, i, route = op.cabin, op.visit, op.route
        t = times[k]
        stop = route.platform_exit_offset_seconds is not None
        current_due = due[k][i]
        conditions = [phase == 0, visits[k] == i, t <= float(p.operation_end)]
        conditions.extend(
            t < other if j < k else t <= other
            for j, other in enumerate(times)
            if j != k
        )
        if stop:
            conditions.append(
                (current_due == 0)
                | (
                    t + float(tick(route.platform_entry_offset_seconds))
                    <= float(p.service_end)
                )
            )
        else:
            conditions.append(current_due == 0)
        next_bound = dp.FloatExpr(float(p.sentinel))
        for j, bound in op.arrival_bounds:
            next_bound = dp.min(
                next_bound,
                (due[k][j] > 0).if_then_else(float(bound), float(p.sentinel)),
            )
        boardbase = t + float(tick(route.platform_exit_offset_seconds)) if stop else t
        upper = (
            (boardbase >= float(p.earliest_wait)).if_then_else(op.maximum_steps, 0)
            if stop
            else 0
        )
        add(
            f"route/{op.index}",
            conditions,
            [
                (phase, 1 if op.candidates else 2),
                (operation, op.index),
                (cursor, 0),
                (load, sum(due[k][i + 1 :], dp.IntExpr(0))),
                (current_due, 0),
                (lo, 0),
                (hi, upper),
                (required, 0.0),
                (latest_board, float(p.sentinel)),
                (latest_next, next_bound),
            ],
            current_due if stop else 0,
            info=("route", op.index),
        )
        bounds = dict(op.arrival_bounds)
        for pos, ride_index in enumerate(op.candidates):
            ride = p.rides[ride_index]
            g = group_index[ride.demand_group_id]
            j = ride.alight_visit_index
            for n in range(min(p.capacity, p.groups[g].count) + 1):
                effects = [
                    (remaining[g], remaining[g] - n),
                    (due[k][j], due[k][j] + n),
                    (load, load + n),
                    (cursor, pos + 1 if pos + 1 < len(op.candidates) else 0),
                    (phase, 1 if pos + 1 < len(op.candidates) else 2),
                ]
                if n:
                    effects.extend(
                        [
                            (
                                required,
                                dp.max(
                                    required,
                                    float(
                                        max(0, tick(p.groups[g].release_time_seconds))
                                    ),
                                ),
                            ),
                            (latest_board, float(p.service_end)),
                            (latest_next, dp.min(latest_next, float(bounds[j]))),
                        ]
                    )
                add(
                    f"take/{op.index}/{pos}/{n}",
                    [
                        phase == 1,
                        operation == op.index,
                        cursor == pos,
                        remaining[g] >= n,
                        load + n <= p.capacity,
                    ],
                    effects,
                    info=("take", ride_index, n),
                )

        def feasible(a, b):
            checks = [
                boardbase + dp.float(b) * float(p.waiting_step) >= required,
                boardbase + dp.float(a) * float(p.waiting_step) <= latest_board,
                t + float(route.duration_tick) + dp.float(a) * float(p.waiting_step)
                <= latest_next,
            ]
            return checks

        mid = lo + (hi - lo) // 2
        add(
            f"split/{op.index}/low",
            [phase == 2, operation == op.index, lo < hi, *feasible(lo, mid)],
            [(hi, mid)],
        )
        add(
            f"split/{op.index}/high",
            [phase == 2, operation == op.index, lo < hi, *feasible(mid + 1, hi)],
            [(lo, mid + 1)],
        )
        add(
            f"wait/{op.index}",
            [phase == 2, operation == op.index, lo == hi, *feasible(lo, hi)],
            [(phase, 3 if route.resource_usages else 4), (cursor, 0)],
        )
        for pos, usage in enumerate(route.resource_usages):
            r = resource_index[usage.resource_id]
            count, entries, ends = calendars[r]
            entry = (
                t
                + float(usage.follower_enter_offset_tick)
                + dp.float(lo)
                * float(p.waiting_step * usage.follower_enter_wait_coefficient)
            )
            end = (
                t
                + float(
                    usage.leader_clear_offset_tick
                    + usage.separation_after_tick(p.resources[r].minimum_headway_tick)
                )
                + dp.float(lo)
                * float(p.waiting_step * usage.leader_clear_wait_coefficient)
            )
            advance = [
                (cursor, pos + 1 if pos + 1 < len(route.resource_usages) else 0),
                (phase, 3 if pos + 1 < len(route.resource_usages) else 4),
            ]
            common = [phase == 3, operation == op.index, cursor == pos]
            add(
                f"reserve/{op.index}/{pos}/outside",
                [*common, entry > float(p.operation_end)],
                advance,
            )
            add(
                f"reserve/{op.index}/{pos}/inside",
                [*common, entry <= float(p.operation_end), end > entry],
                [
                    (phase, 5),
                    (pending_resource, r),
                    (pending_entry, entry),
                    (pending_end, end),
                    (
                        resume_cursor,
                        pos + 1 if pos + 1 < len(route.resource_usages) else 0,
                    ),
                    (resume_phase, 3 if pos + 1 < len(route.resource_usages) else 4),
                ],
            )
        add(
            f"commit/{op.index}",
            [phase == 4, operation == op.index],
            [
                (
                    times[k],
                    t
                    + float(route.duration_tick)
                    + dp.float(lo) * float(p.waiting_step),
                ),
                (visits[k], i + 1),
                (phase, 0),
                (operation, -1),
                (cursor, 0),
                (load, 0),
                (lo, 0),
                (hi, 0),
                (required, 0.0),
                (latest_board, float(p.sentinel)),
                (latest_next, float(p.sentinel)),
            ],
            info=("commit", op.index),
        )
    # One native calendar insertion per resource, shared across all visits.
    for r, (count, entries, ends) in enumerate(calendars):
        conditions = [phase == 5, pending_resource == r, count < len(entries)]
        conditions.extend(
            (count <= z) | (pending_end <= entry) | (pending_entry >= end)
            for z, (entry, end) in enumerate(zip(entries, ends))
        )
        conditions.extend(
            (pending_end <= float(entry)) | (pending_entry >= float(end))
            for entry, end in p.boundaries[r]
        )
        rank = m.add_int_state_fun(
            sum(
                (
                    ((count > z) & (entry < pending_entry)).if_then_else(1, 0)
                    for z, entry in enumerate(entries)
                ),
                dp.IntExpr(0),
            )
        )
        effects = [
            (count, count + 1),
            (phase, resume_phase),
            (cursor, resume_cursor),
            (pending_resource, -1),
            (pending_entry, 0.0),
            (pending_end, 0.0),
            (resume_phase, 0),
            (resume_cursor, 0),
        ]
        for z in range(len(entries)):
            effects.extend(
                [
                    (
                        entries[z],
                        (rank > z).if_then_else(
                            entries[z],
                            (rank == z).if_then_else(
                                pending_entry, entries[max(0, z - 1)]
                            ),
                        ),
                    ),
                    (
                        ends[z],
                        (rank > z).if_then_else(
                            ends[z],
                            (rank == z).if_then_else(pending_end, ends[max(0, z - 1)]),
                        ),
                    ),
                ]
            )
        add(f"insert/{r}", conditions, effects)
    m.add_base_case(
        [
            phase == 0,
            *[t > float(p.operation_end) for t in times],
            *[amount == 0 for cabin in due for amount in cabin],
        ],
        cost=0,
    )
    # Each promised or unassigned person can contribute at most once. Omitting
    # capacity/resource competition is optimistic, hence safe for maximization.
    bound = sum((x for cabin in due for x in cabin), dp.IntExpr(0))
    for g, amount in zip(p.groups, remaining):
        if tick(g.release_time_seconds) <= p.service_end:
            bound += (now <= float(p.service_end)).if_then_else(amount, 0)
    m.add_dual_bound(bound)
    return BuiltDidpModel(p, m, v, transitions, metadata)
