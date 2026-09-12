"""Anonymous visit-layer/time-cell relaxation, without waiting tick expansion.

Visit layers prevent unanchored same-cell circulations. They are occurrence
indices, not cabin labels. Every original single-use trip has a direct image.
"""

from dataclasses import dataclass
from time import perf_counter

from ..models import DddRouteDecision
from ..time_ticks import ddd_seconds_to_tick as tick


@dataclass(frozen=True)
class TimeRegion:
    """t = route entry, u = t + waiting; integer-bound rectangle and strip."""

    tlo: int
    thi: int
    ulo: int
    uhi: int
    wlo: int
    whi: int

    def vertices(self):
        candidates = {
            (t, u) for t in (self.tlo, self.thi) for u in (self.ulo, self.uhi)
        }
        candidates.update(
            (t, t + w) for t in (self.tlo, self.thi) for w in (self.wlo, self.whi)
        )
        candidates.update(
            (u - w, u) for u in (self.ulo, self.uhi) for w in (self.wlo, self.whi)
        )
        return tuple(
            sorted(
                (t, u)
                for t, u in candidates
                if self.tlo <= t <= self.thi
                and self.ulo <= u <= self.uhi
                and self.wlo <= u - t <= self.whi
            )
        )


@dataclass(frozen=True)
class BoundArc:
    id: int
    visit: int
    source: int
    target: int
    option_id: str
    vertices: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class PreparedReservoirBound:
    problem: object
    partition: object
    arcs: tuple[BoundArc, ...]
    dispatch_nodes: tuple[tuple[int, int], ...]
    return_nodes: tuple[tuple[int, int], ...]
    build_seconds: float


def check_deadline(deadline):
    if deadline is not None and perf_counter() >= deadline:
        raise TimeoutError("reservoir bound deadline")


def prepare_bound(problem, partition, deadline=None):
    started = perf_counter()
    problem.validate()
    states = problem.visit_states
    opts = problem.resolved_core.route_options_by_state_id
    end = problem.resolved_core.operational_end_tick
    first = tick(problem.dispatch_start_seconds)
    last = tick(problem.dispatch_end_seconds)
    minimum = {s: min(o.duration_tick for o in opts[s]) for s in problem.cycle_states}
    remainder = {}
    for s in problem.cycle_states:
        state, duration = s, 0
        while state != problem.entry_state_id:
            duration += minimum[state]
            state = opts[state][0].to_state_id
        remainder[s] = duration
    earliest = first
    nodes = []
    for i, s in enumerate(states):
        cells = []
        upper = min(end - remainder[s], last if i == 0 else end)
        for c in range(len(partition.points) - 1):
            lo, hi = partition.bounds(c)
            lo, hi = max(lo, earliest), min(hi, upper)
            if lo <= hi:
                cells.append((c, lo, hi))
        nodes.append(cells)
        earliest += minimum[s]
    arcs = []
    step = tick(problem.waiting_policy.step_seconds or 0.000001)
    allowed = tick(problem.waiting_policy.earliest_wait_time_seconds)
    for i, s in enumerate(states[:-1]):
        check_deadline(deadline)
        for o in opts[s]:
            maximum = (
                tick(problem.waiting_policy.maximum_wait_seconds(o.station_id))
                // step
                * step
                if o.decision is DddRouteDecision.STOP
                else 0
            )
            for c, lo, hi in nodes[i]:
                for d, nlo, nhi in nodes[i + 1]:
                    ulo, uhi = nlo - o.duration_tick, nhi - o.duration_tick
                    v = set(TimeRegion(lo, hi, ulo, uhi, 0, 0).vertices())
                    if maximum:
                        positive_lo = max(
                            lo, allowed - tick(o.platform_exit_offset_seconds)
                        )
                        v.update(
                            TimeRegion(
                                positive_lo, hi, ulo, uhi, step, maximum
                            ).vertices()
                        )
                    if v:
                        arcs.append(
                            BoundArc(len(arcs), i, c, d, o.id, tuple(sorted(v)))
                        )
    # Reachability prune only arcs not belonging to a complete dispatch-return path.
    dispatch = {(0, c) for c, _, _ in nodes[0]}
    returns = {
        (i, c)
        for i, s in enumerate(states)
        if i and s == problem.entry_state_id
        for c, _, hi in nodes[i]
        if hi >= tick(problem.return_start_seconds)
    }
    forward = set(dispatch)
    for a in arcs:
        # Arcs are sorted by visit, so no per-tick fixed point is necessary.
        if (a.visit, a.source) in forward:
            forward.add((a.visit + 1, a.target))
    backward = set(returns)
    for a in reversed(arcs):
        if (a.visit + 1, a.target) in backward:
            backward.add((a.visit, a.source))
    arcs = tuple(
        a
        for a in arcs
        if (a.visit, a.source) in forward and (a.visit + 1, a.target) in backward
    )
    return PreparedReservoirBound(
        problem,
        partition,
        arcs,
        tuple(sorted(dispatch & backward)),
        tuple(sorted(returns & forward)),
        perf_counter() - started,
    )


def minimum_overlap(arc, usage, resource, left, right):
    """Exact minimum over the continuous local polygons, hence a safe tick LB.

    min(end,R)-max(entry,L) is concave in (t,u), so its minimum is at a
    polygon vertex. max(0,.) commutes with taking that minimum. Both the zero
    and positive-wait polygons' vertices are included; no tick enumeration.
    """
    result = None
    for t, u in arc.vertices:
        enter = (
            u if usage.follower_enter_wait_coefficient else t
        ) + usage.follower_enter_offset_tick
        clear = (
            (u if usage.leader_clear_wait_coefficient else t)
            + usage.leader_clear_offset_tick
            + usage.separation_after_tick(resource.minimum_headway_tick)
        )
        overlap = max(0, min(clear, right) - max(enter, left))
        result = overlap if result is None else min(result, overlap)
    return result or 0
