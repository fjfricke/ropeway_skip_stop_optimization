"""Solver-free immutable passenger algebra on the original exact phase graph."""

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, fields
from time import perf_counter

from ...ean.models import EanDemandGroup
from ..cp_sat_certificate import stable_fingerprint
from ..time_ticks import ddd_seconds_to_tick as tick
from .network import check


@dataclass(frozen=True)
class PassengerGroup:
    id: str
    class_id: str
    count: int
    release: int
    origin: str
    destination: str
    support: tuple[int, ...]
    boarding: tuple[int, ...]
    alighting: tuple[int, ...]


@dataclass(frozen=True)
class PassengerVariable:
    key: tuple
    upper: int
    boarding: bool = False
    boundary: bool = False


@dataclass(frozen=True)
class PassengerRow:
    family: str
    terms: tuple
    sense: str
    rhs: int


@dataclass(frozen=True)
class PreparedPassengerStructure:
    encoding: str
    groups: tuple[PassengerGroup, ...]
    variables: tuple[PassengerVariable, ...]
    rows: tuple[PassengerRow, ...]
    loads: tuple
    alighting: tuple
    projection: tuple
    queue_steps: tuple
    removed_equalities: int
    fingerprint: str
    seconds: float


def group_flow_key(g, aid, encoding):
    if encoding == "legacy" or encoding == "od_flow" and aid in g.boarding:
        return ("g", g.id, aid)
    return ("od", g.class_id, aid)


def _reach(nodes, adjacency):
    seen = set(nodes)
    pending = list(seen)
    while pending:
        for n in adjacency[pending.pop()]:
            if n not in seen:
                seen.add(n)
                pending.append(n)
    return seen


def prepare_passengers(network, config, deadline=None):
    start = perf_counter()
    config.validate()
    p = network.problem
    encoding = config.passenger_encoding
    # Current domain has no group deadlines, priorities or alternative routes.
    # Refuse extended records until their interchangeability is explicitly proved.
    if encoding != "legacy":
        expected = {
            "id",
            "origin_station_id",
            "destination_station_id",
            "release_time_seconds",
            "count",
        }
        if {f.name for f in fields(EanDemandGroup)} != expected or any(
            type(g) is not EanDemandGroup for g in p.demand_groups
        ):
            raise ValueError("unsupported group contract for OD aggregation")
    options = {o.id: o for o in p.resolved_core.route_options}
    states = p.cycle_states
    station = {
        s: next(o.station_id for o in options.values() if o.from_state_id == s)
        for s in states
    }
    if len(set(station.values())) != len(states):
        raise ValueError(
            "passenger classes require unique station states on the directed cycle"
        )
    groups = []
    arcmap = {a.id: a for a in network.arcs}
    for g in p.demand_groups:
        check(deadline)
        origin = next(s for s in states if station[s] == g.origin_station_id)
        dest = next(s for s in states if station[s] == g.destination_station_id)
        oi = states.index(origin)
        distance = (states.index(dest) - oi) % len(states)
        candidates, boards, alights = [], [], []
        adj, rev = defaultdict(list), defaultdict(list)
        for a in network.arcs:
            if a.option_id is None:
                continue
            s = options[a.option_id].from_state_id
            d = (states.index(s) - oi) % len(states)
            if (
                0 < d < distance
                or d == 0
                and a.kind == "exit"
                and a.source[2] >= tick(g.release_time_seconds)
                or d == distance
                and a.kind == "arrive"
                and a.target[2] <= p.resolved_core.passenger_service_end_tick
            ):
                candidates.append(a)
                adj[a.source].append(a.target)
                rev[a.target].append(a.source)
                if s == origin:
                    boards.append(a)
                if s == dest:
                    alights.append(a)
        fwd = _reach([a.source for a in boards], adj)
        bwd = _reach([a.target for a in alights], rev)
        support = tuple(a.id for a in candidates if a.source in fwd and a.target in bwd)
        keep = set(support)
        # Same cycle and destination rule for every member: after a valid boarding,
        # releases are past and all continuations to the first destination coincide.
        cid = stable_fingerprint(
            (origin, dest, tuple(states), p.resolved_core.passenger_service_end_tick)
        )
        groups.append(
            PassengerGroup(
                g.id,
                cid,
                g.count,
                tick(g.release_time_seconds),
                origin,
                dest,
                support,
                tuple(a.id for a in boards if a.id in keep),
                tuple(a.id for a in alights if a.id in keep),
            )
        )
    variables, loads, sinks = {}, defaultdict(set), set()
    conservation = defaultdict(Counter)
    balances, demands = defaultdict(Counter), defaultdict(Counter)
    classes = defaultdict(list)
    for g in groups:
        classes[g.class_id].append(g)
    for g in groups:
        block = g.id if encoding == "legacy" else g.class_id
        boards, alights = set(g.boarding), set(g.alighting)
        balances[block]  # retain the legacy empty delivered-balance row
        for aid in g.support:
            key = (
                ("g", g.id, aid)
                if encoding == "legacy" or encoding == "od_flow" and aid in boards
                else ("od", g.class_id, aid)
            )
            # A shared variable is represented once in every conservation/load row.
            if key in variables:
                continue
            a = arcmap[aid]
            board, alight = aid in boards, aid in alights
            upper = (
                min(g.count, p.cabin_capacity)
                if key[0] == "g"
                else min(sum(h.count for h in classes[g.class_id]), p.cabin_capacity)
            )
            variables[key] = PassengerVariable(key, upper, board, board or alight)
            loads[aid].add(key)
            if board:
                balances[block][key] += 1
                if encoding == "legacy" or encoding == "od_flow":
                    demands[g.id][key] += 1
            else:
                conservation[block, a.source][key] -= 1
            if alight:
                balances[block][key] -= 1
                sinks.add(key)
            else:
                conservation[block, a.target][key] += 1
    rows = []

    def add(family, terms, sense="=", rhs=0):
        rows.append(
            PassengerRow(
                family, tuple(sorted((k, v) for k, v in terms.items() if v)), sense, rhs
            )
        )

    for terms in conservation.values():
        add("passenger_flow", terms)
    for terms in balances.values():
        add("delivered_balance", terms)
    queue_steps = []
    if encoding != "od_queue":
        for g in groups:
            add("demand", demands[g.id], "<", g.count)
    else:
        for cid, members in sorted(classes.items()):
            releases, boarding = Counter(), defaultdict(list)
            for g in members:
                releases[g.release] += g.count
            for key, v in variables.items():
                if key[:2] == ("od", cid) and v.boarding:
                    boarding[arcmap[key[2]].source[2]].append(key)
            previous = None
            for t in sorted(releases.keys() | boarding.keys()):
                key = ("queue", cid, t)
                variables[key] = PassengerVariable(
                    key, sum(g.count for g in members), boundary=True
                )
                terms = Counter({key: 1})
                if previous is not None:
                    terms[previous] -= 1
                for b in boarding[t]:
                    terms[b] += 1
                add("demand_queue", terms, "=", releases[t])
                queue_steps.append((key, previous, releases[t], tuple(boarding[t])))
                previous = key
    projection = {k: k for k in variables}
    removed = 0
    if config.passenger_network == "contracted":

        def root(k):
            path = []
            while projection[k] != k:
                path.append(k)
                k = projection[k]
            for x in path:
                projection[x] = k
            return k

        for row in rows:
            check(deadline)
            if row.family != "passenger_flow" or len(row.terms) != 2:
                continue
            (a, ca), (b, cb) = row.terms
            if (
                ca != -cb
                or abs(ca) != 1
                or variables[a].boundary
                or variables[b].boundary
            ):
                continue
            ra, rb = root(a), root(b)
            if ra != rb:
                projection[max(ra, rb)] = min(ra, rb)
        projection = {k: root(k) for k in variables}
        newvars = {}
        for key, v in variables.items():
            rep = projection[key]
            upper = min(v.upper, newvars[rep].upper) if rep in newvars else v.upper
            newvars[rep] = PassengerVariable(rep, upper, v.boarding, v.boundary)
        newrows = []
        for r in rows:
            terms = Counter()
            for k, coef in r.terms:
                terms[projection[k]] += coef
            terms = tuple(sorted((k, c) for k, c in terms.items() if c))
            if not terms and r.rhs == 0 and r.sense == "=":
                removed += 1
            else:
                newrows.append(PassengerRow(r.family, terms, r.sense, r.rhs))
        variables, rows = newvars, newrows
    # Capacity occurrences keep multiplicities after substitution. In the current
    # chain transform at most one member per class/physical arc is present.
    normalized_loads = []
    for aid, keys in sorted(loads.items()):
        terms = Counter(projection[k] for k in keys)
        normalized_loads.append((aid, tuple(sorted(terms.items()))))
    data = dict(
        encoding=encoding,
        groups=tuple(groups),
        variables=tuple(variables.values()),
        rows=tuple(rows),
        loads=tuple(normalized_loads),
        alighting=tuple(sorted(projection[k] for k in sinks)),
        projection=tuple(sorted(projection.items())),
        queue_steps=tuple(queue_steps),
        removed_equalities=removed,
    )
    check(deadline)
    return PreparedPassengerStructure(
        **data,
        fingerprint=stable_fingerprint(
            data
            | {
                k: tuple(asdict(x) for x in data[k])
                for k in ("groups", "variables", "rows")
            }
        ),
        seconds=perf_counter() - start,
    )
