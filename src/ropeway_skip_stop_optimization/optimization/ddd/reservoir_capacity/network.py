"""Exact phase graph on a declared, finite set of candidate times.

No physical time is rounded. Completeness is only claimed for the recorded
graph. In particular its infeasibility and MIP bound are not global statements.
"""

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from time import perf_counter

from ..cp_sat_certificate import stable_fingerprint
from ..models import DddRouteDecision as Decision
from ..reservoir_cp_sat_certificate import validate_reservoir_cp_plan
from ..time_ticks import ddd_seconds_to_tick as tick

Node = tuple[str, str, int]


def check(deadline):
    if deadline is not None and perf_counter() >= deadline:
        raise TimeoutError("capacity graph/model deadline; domain not truncated")


@dataclass(frozen=True)
class PhaseGeometry:
    option_id: str
    arrival: int
    ready: int
    waiting_resources: tuple[str, ...]


@dataclass(frozen=True)
class PhaseArc:
    id: int
    source: Node | None
    target: Node | None
    kind: str
    option_id: str | None
    # Half-open, fully protected intervals; never clipped at the horizon.
    resources: tuple[tuple[str, int, int], ...] = ()


@dataclass(frozen=True)
class PhaseNetwork:
    problem: object
    arcs: tuple[PhaseArc, ...]
    geometry: tuple[PhaseGeometry, ...]
    dispatch_ticks: tuple[int, ...]
    profile: str
    fingerprint: str
    build_seconds: float
    removed_arcs: int


def prepare_geometry(problem):
    problem.validate()
    core = problem.resolved_core
    result = []
    for o in core.route_options:
        if o.decision is Decision.SKIP:
            if any(
                u.follower_enter_wait_coefficient or u.leader_clear_wait_coefficient
                for u in o.resource_usages
            ):
                raise ValueError("SKIP waiting coefficients unsupported")
            continue
        a, e = (
            tick(o.platform_entry_offset_seconds),
            tick(o.platform_exit_offset_seconds),
        )
        if not 0 <= a <= e < o.duration_tick:
            raise ValueError("unsupported STOP phase ordering")
        holding = []
        for u in o.resource_usages:
            coefficients = (
                u.follower_enter_wait_coefficient,
                u.leader_clear_wait_coefficient,
            )
            if coefficients == (0, 1):
                if u.follower_enter_offset_tick != e or u.leader_clear_offset_tick < e:
                    raise ValueError("waiting resource must begin at exit-ready")
                holding.append(u.resource_id)
            elif coefficients not in ((0, 0), (1, 1)):
                raise ValueError("unsupported phase resource coefficients")
        if (
            problem.waiting_policy.maximum_wait_seconds(o.station_id) > 0
            and not holding
        ):
            raise ValueError(
                "compact waiting requires a physical single-occupancy exit resource"
            )
        result.append(PhaseGeometry(o.id, a, e, tuple(holding)))
    for state in problem.cycle_states:
        if (
            sum(
                o.from_state_id == state and o.decision is Decision.STOP
                for o in core.route_options
            )
            != 1
        ):
            raise ValueError("phase pilot requires one STOP alternative per station")
    return tuple(result)


def build_network(
    problem,
    references=(),
    *,
    deadline=None,
    dispatch_spacing_tick=30_000_000,
    expansion_rounds=2,
    exact_entry_times=None,
    exact_exit_times=None,
):
    """seed_events_v1; explicit calendars are reserved for enumerated controls."""
    started = perf_counter()
    geometry = prepare_geometry(problem)
    core = problem.resolved_core
    options = {o.id: o for o in core.route_options}
    geo = {g.option_id: g for g in geometry}
    stops = {
        o.from_state_id: o for o in options.values() if o.decision is Decision.STOP
    }
    H = core.operational_end_tick
    if (
        H
        + max(o.duration_tick for o in options.values())
        + max(
            (
                tick(problem.waiting_policy.maximum_wait_seconds(o.station_id))
                for o in options.values()
            ),
            default=0,
        )
        >= 2**53
    ):
        raise ValueError("phase timestamps exceed exact integer range")
    lo, hi = tick(problem.dispatch_start_seconds), tick(problem.dispatch_end_seconds)
    step = tick(problem.dispatch_step_seconds)
    if dispatch_spacing_tick <= 0 or expansion_rounds < 0:
        raise ValueError("invalid calendar parameters")
    entries, exits = defaultdict(set), defaultdict(set)
    seed_dispatch = set()
    for plan in references:
        validate_reservoir_cp_plan(problem, plan)
        for tr in plan.trips:
            seed_dispatch.add(tr.switch_ticks[0])
            for oid, t, w in zip(tr.route_option_ids, tr.switch_ticks, tr.wait_ticks):
                o = options[oid]
                entries[o.from_state_id].add(t)
                entries[o.to_state_id].add(t + o.duration_tick + w)
                if o.decision is Decision.STOP:
                    exits[o.from_state_id].update(
                        (t + geo[oid].ready, t + geo[oid].ready + w)
                    )
                for u in o.resource_usages:
                    end = (
                        t
                        + u.leader_clear_offset_tick
                        + u.leader_clear_wait_coefficient * w
                    )
                    end += u.separation_after_tick(
                        core.resources_by_id[u.resource_id].minimum_headway_tick
                    )
                    exits[o.from_state_id].add(end)
    anchors = {lo, hi} | seed_dispatch | set(range(lo, hi + 1, dispatch_spacing_tick))
    ordered = sorted(seed_dispatch)
    anchors.update((a + b) // 2 for a, b in zip(ordered, ordered[1:]))
    anchors = {t for t in anchors if lo <= t <= hi and (t - lo) % step == 0}
    if exact_entry_times is None:
        for dispatch in sorted(anchors):
            for decision in (Decision.STOP, Decision.SKIP):
                state, t = problem.entry_state_id, dispatch
                while t <= H:
                    check(deadline)
                    entries[state].add(t)
                    possible = [
                        o
                        for o in core.route_options_by_state_id[state]
                        if o.decision is decision
                    ]
                    if not possible:
                        break
                    o = possible[0]
                    if decision is Decision.STOP:
                        exits[state].add(t + geo[o.id].ready)
                    t, state = t + o.duration_tick, o.to_state_id
        for g in problem.demand_groups:
            for state, o in stops.items():
                if o.station_id == g.origin_station_id:
                    exits[state].add(tick(g.release_time_seconds))
        for _ in range(expansion_rounds):
            additions = defaultdict(set)
            for state, times in list(entries.items()):
                for t in sorted(times):
                    check(deadline)
                    for o in core.route_options_by_state_id[state]:
                        if t + o.duration_tick <= H:
                            additions[o.to_state_id].add(t + o.duration_tick)
                            if o.decision is Decision.STOP:
                                exits[state].add(t + geo[o.id].ready)
            for state, times in list(exits.items()):
                o = stops[state]
                for t in times:
                    end = t + o.duration_tick - geo[o.id].ready
                    if 0 <= t and end <= H:
                        additions[o.to_state_id].add(end)
            for state, ts in additions.items():
                entries[state].update(ts)
    else:
        entries = defaultdict(set, {s: set(ts) for s, ts in exact_entry_times.items()})
        exits = defaultdict(
            set, {s: set(ts) for s, ts in (exact_exit_times or {}).items()}
        )
        anchors = {
            t
            for t in entries[problem.entry_state_id]
            if lo <= t <= hi and (t - lo) % step == 0
        }
    arcs = []

    def add(source, target, kind, oid=None, resources=()):
        arcs.append(PhaseArc(len(arcs), source, target, kind, oid, tuple(resources)))

    def usages(o, t, phase):
        intervals = []
        for u in o.resource_usages:
            coefficients = (
                u.follower_enter_wait_coefficient,
                u.leader_clear_wait_coefficient,
            )
            r = core.resources_by_id[u.resource_id]
            h = u.separation_after_tick(r.minimum_headway_tick)
            if phase == "prefix" and coefficients == (0, 0):
                a, b = (
                    t + u.follower_enter_offset_tick,
                    t + u.leader_clear_offset_tick + h,
                )
            elif phase == "exit" and coefficients == (1, 1):
                a = t + u.follower_enter_offset_tick - geo[o.id].ready
                b = t + u.leader_clear_offset_tick - geo[o.id].ready + h
            elif phase == "exit" and coefficients == (0, 1):
                a, b = t, t + u.leader_clear_offset_tick - geo[o.id].ready + h
            else:
                continue
            if b <= a:
                raise ValueError("nonpositive protected phase interval")
            if a <= H:
                intervals.append((r.id, a, b))
        return intervals

    for state in problem.cycle_states:
        for t in sorted(entries[state]):
            check(deadline)
            if not 0 <= t <= H:
                continue
            n = (state, "entry", t)
            if state == problem.entry_state_id:
                if t in anchors:
                    add(None, n, "dispatch")
                if tick(problem.return_start_seconds) <= t:
                    add(n, None, "return")
            for o in core.route_options_by_state_id[state]:
                if o.decision is Decision.SKIP:
                    if t + o.duration_tick in entries[o.to_state_id]:
                        add(
                            n,
                            (o.to_state_id, "entry", t + o.duration_tick),
                            "skip",
                            o.id,
                            usages(o, t, "prefix"),
                        )
                elif t + geo[o.id].ready <= H:
                    arrival = (state, "arrival", t + geo[o.id].arrival)
                    ready = (state, "waiting", t + geo[o.id].ready)
                    add(n, arrival, "arrive", o.id, usages(o, t, "prefix"))
                    add(arrival, ready, "ready", o.id)
                    exits[state].add(ready[2])
        o = stops[state]
        # Different waiting-step residues cannot be connected by a hold edge.
        wstep = tick(problem.waiting_policy.step_seconds or 0.000001)
        by_residue = defaultdict(list)
        for d in sorted(exits[state]):
            if not 0 <= d <= H:
                continue
            by_residue[d % wstep].append(d)
            end = d + o.duration_tick - geo[o.id].ready
            if end in entries[o.to_state_id]:
                add(
                    (state, "waiting", d),
                    (o.to_state_id, "entry", end),
                    "exit",
                    o.id,
                    usages(o, d, "exit"),
                )
        if problem.waiting_policy.maximum_wait_seconds(o.station_id) > 0:
            for times in by_residue.values():
                for a, b in zip(times, times[1:]):
                    if a >= tick(problem.waiting_policy.earliest_wait_time_seconds):
                        add(
                            (state, "waiting", a),
                            (state, "waiting", b),
                            "hold",
                            o.id,
                            ((r, a, b) for r in geo[o.id].waiting_resources),
                        )
    # Reachability has no physical relaxation: unsupported boundary arcs disappear.
    outgoing, incoming = defaultdict(list), defaultdict(list)
    for a in arcs:
        if a.source is not None:
            outgoing[a.source].append(a)
        if a.target is not None:
            incoming[a.target].append(a)

    def reach(initial, adjacency, endpoint):
        found, queue = set(initial), deque(initial)
        while queue:
            check(deadline)
            for a in adjacency[queue.popleft()]:
                n = getattr(a, endpoint)
                if n is not None and n not in found:
                    found.add(n)
                    queue.append(n)
        return found

    fwd = reach([a.target for a in arcs if a.kind == "dispatch"], outgoing, "target")
    bwd = reach([a.source for a in arcs if a.kind == "return"], incoming, "source")
    kept = tuple(
        a
        for a in arcs
        if (a.source is None or a.source in fwd)
        and (a.target is None or a.target in bwd)
    )
    identity = stable_fingerprint(
        {
            "domain": problem.fingerprint,
            "profile": "seed_events_v1",
            "dispatch_spacing": dispatch_spacing_tick,
            "rounds": expansion_rounds,
            "arcs": [asdict(a) for a in kept],
        }
    )
    result = PhaseNetwork(
        problem,
        kept,
        geometry,
        tuple(sorted(anchors)),
        "seed_events_v1",
        identity,
        perf_counter() - started,
        len(arcs) - len(kept),
    )
    for plan in references:
        replay_paths(result, plan)
    return result


def replay_paths(network, plan):
    """Map a validated original certificate without solving or changing it."""
    validate_reservoir_cp_plan(network.problem, plan)
    by_key = {(a.kind, a.option_id, a.source): a for a in network.arcs}
    outgoing = defaultdict(list)
    for a in network.arcs:
        outgoing[a.source].append(a)
    options = {o.id: o for o in network.problem.resolved_core.route_options}
    paths = {}
    for tr in plan.trips:
        first = (network.problem.entry_state_id, "entry", tr.switch_ticks[0])
        dispatch = next(
            (a for a in network.arcs if a.kind == "dispatch" and a.target == first),
            None,
        )
        if dispatch is None:
            raise ValueError("reference dispatch absent from restricted graph")
        path = [dispatch]
        for oid, t, w in zip(tr.route_option_ids, tr.switch_ticks, tr.wait_ticks):
            o = options[oid]
            node = (o.from_state_id, "entry", t)
            kinds = ("skip",) if o.decision is Decision.SKIP else ("arrive", "ready")
            for kind in kinds:
                a = by_key.get((kind, oid, node))
                if a is None:
                    raise ValueError("reference movement absent from restricted graph")
                path.append(a)
                node = a.target
            if o.decision is Decision.STOP:
                target = node[2] + w
                while node[2] < target:
                    a = by_key.get(("hold", oid, node))
                    if a is None or a.target[2] > target:
                        raise ValueError("reference wait absent from graph")
                    path.append(a)
                    node = a.target
                a = by_key.get(("exit", oid, node))
                if a is None:
                    raise ValueError("reference exit absent from graph")
                path.append(a)
        a = by_key.get(
            ("return", None, (network.problem.entry_state_id, "entry", tr.return_tick))
        )
        if a is None:
            raise ValueError("reference return absent from graph")
        path.append(a)
        paths[tr.cabin_id] = tuple(path)
    return paths
