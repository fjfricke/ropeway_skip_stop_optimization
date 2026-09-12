"""Exact group projection and deterministic lifting; no optimization or repair."""

from collections import Counter, defaultdict

from .passenger_structure import group_flow_key


def integer(value):
    n = round(value)
    if abs(value - n) > 1e-5:
        raise ValueError("nonintegral native certificate value")
    return n


def assign_released(groups, boardings):
    """Lift (tick, cabin, arc, count) events to original released group counts."""
    remaining = {g.id: g.count for g in groups}
    ordered = sorted(groups, key=lambda g: (g.release, g.id))
    assignments = Counter()
    for t, cabin, aid, count in sorted(boardings):
        n = integer(count)
        if n < 0:
            raise ValueError("negative boarding")
        for g in ordered:
            if g.release > t:
                break
            take = min(n, remaining[g.id])
            if take:
                assignments[cabin, aid, g.id] += take
                remaining[g.id] -= take
                n -= take
            if not n:
                break
        if n:
            raise ValueError("boarding exceeds released demand")
    return assignments


def reference_values(passengers, plan, paths):
    structure = passengers.structure
    p = passengers.network.problem
    groups = {g.id: g for g in structure.groups}
    projection = dict(structure.projection)
    supports = {g.id: set(g.support) for g in structure.groups}
    raw = dict.fromkeys(projection, 0)
    rides = {r.id: r for r in p.passenger_build.ride_candidates}
    visits = {}
    for k, path in paths.items():
        i = -1
        for a in path:
            if a.kind in ("arrive", "skip"):
                i += 1
            visits[k, a.id] = i
    for rid, n in plan.ride_counts.items():
        if not n:
            continue
        if rid not in rides:
            raise ValueError("unknown positive reference ride")
        r = rides[rid]
        g = groups[r.demand_group_id]
        for a in paths[r.cabin_id]:
            i = visits[r.cabin_id, a.id]
            if (
                r.board_visit_index < i < r.alight_visit_index
                or i == r.board_visit_index
                and a.kind == "exit"
                or i == r.alight_visit_index
                and a.kind == "arrive"
            ):
                key = group_flow_key(g, a.id, structure.encoding)
                if a.id not in supports[g.id] or key not in raw:
                    raise ValueError("positive reference ride not representable")
                raw[key] += n
    for key, previous, released, boarding in structure.queue_steps:
        raw[key] = (
            (raw[previous] if previous else 0)
            + released
            - sum(raw[b] for b in boarding)
        )
    values = {}
    for key, rep in projection.items():
        index = passengers.variables[rep].index
        if index in values and values[index] != raw[key]:
            raise ValueError("reference contradicts contracted passenger equality")
        values[index] = raw[key]
    return values


def extract_assignment(passengers, value, paths):
    """Board on concrete cabin paths, then discharge at the first destination."""
    st = passengers.structure
    p = passengers.network.problem
    proj = dict(st.projection)
    groups = {g.id: g for g in st.groups}
    classes = defaultdict(list)
    for g in st.groups:
        classes[g.class_id].append(g)

    def get(key):
        return integer(value(passengers.variables[proj[key]])) if key in proj else 0

    assignments = Counter()
    if st.encoding == "od_queue":
        events = defaultdict(list)
        for k, path in paths.items():
            for a in path:
                if a.kind != "exit":
                    continue
                for cid, members in classes.items():
                    if members[0].origin == a.source[0]:
                        n = get(("od", cid, a.id))
                        if n:
                            events[cid].append((a.source[2], k, a.id, n))
        for cid, events_c in events.items():
            assignments.update(assign_released(classes[cid], events_c))
    else:
        boarding_groups = defaultdict(list)
        for g in st.groups:
            for aid in g.boarding:
                boarding_groups[aid].append(g)
        for k, path in paths.items():
            for a in path:
                if a.kind == "exit":
                    for g in boarding_groups[a.id]:
                        n = get(("g", g.id, a.id))
                        if n:
                            assignments[k, a.id, g.id] = n
    candidates = {
        (r.cabin_id, r.demand_group_id, r.board_visit_index, r.alight_visit_index): r.id
        for r in p.passenger_build.ride_candidates
    }
    counts = {}
    for k, path in paths.items():
        onboard = {}
        visit = -1
        for a in path:
            if a.kind in ("arrive", "skip"):
                visit += 1
            if a.kind == "arrive":
                for gid in list(onboard):
                    g = groups[gid]
                    if g.destination == a.source[0]:
                        board, n = onboard.pop(gid)
                        rid = candidates.get((k, gid, board, visit))
                        if rid is None:
                            raise ValueError("lift produced a noncanonical ride")
                        counts[rid] = n
            if a.kind == "skip":
                if any(groups[gid].destination == a.source[0] for gid in onboard):
                    raise ValueError("SKIP with an outstanding destination obligation")
            if a.kind == "exit":
                for g in st.groups:
                    n = assignments[k, a.id, g.id]
                    if n:
                        if (
                            g.id in onboard
                            or g.origin != a.source[0]
                            or g.release > a.source[2]
                        ):
                            raise ValueError(
                                "invalid boarding or additional passenger round"
                            )
                        onboard[g.id] = (visit, n)
            if sum(n for _, n in onboard.values()) > p.cabin_capacity:
                raise ValueError("lift exceeds cabin capacity")
        if onboard:
            raise ValueError("unfulfilled passenger obligation")
    return counts
