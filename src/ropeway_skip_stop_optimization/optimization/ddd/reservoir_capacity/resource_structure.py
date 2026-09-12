"""Coefficient-aware redundant rows and bounded, certified cross-resource cuts."""

from collections import defaultdict
from dataclasses import asdict, dataclass
from itertools import combinations
from time import perf_counter

from ..cp_sat_certificate import stable_fingerprint
from .network import check


@dataclass(frozen=True)
class ResourceRow:
    resource: str
    tick: int
    terms: tuple


@dataclass(frozen=True)
class PreparedResources:
    rows: tuple
    retained: tuple
    implied_by: tuple
    cliques: tuple
    pair_witnesses: tuple
    work: int
    truncated: bool
    fingerprint: str
    seconds: float


def dominates(stronger, weaker):
    strong = dict(stronger)
    return all(strong.get(k, 0) >= v for k, v in weaker)


def prepare_resources(arcs, config, deadline=None):
    started = perf_counter()
    uses = defaultdict(list)
    for a in arcs:
        for resource, left, right in a.resources:
            uses[resource].append((left, right, a.id))
    rows = []
    for rid, intervals in uses.items():
        events = defaultdict(lambda: [[], []])
        for left, right, aid in intervals:
            if right <= left:
                raise ValueError(
                    "resource interval must have positive protected length"
                )
            events[left][1].append(aid)
            events[right][0].append(aid)
        active = defaultdict(int)
        for t, (ends, starts) in sorted(events.items()):
            check(deadline)
            for aid in ends:
                active[aid] -= 1
                if not active[aid]:
                    del active[aid]
            for aid in starts:
                active[aid] += 1
            if starts and sum(active.values()) > 1:
                rows.append(ResourceRow(rid, t, tuple(sorted(active.items()))))
    removed = {}
    if config.resource_encoding == "maximal":
        identical = {}
        previous = None
        for i, r in enumerate(rows):
            check(deadline)
            if r.terms in identical:
                removed[i] = identical[r.terms]
            else:
                identical[r.terms] = i
                if previous is not None and rows[previous].resource == r.resource:
                    if dominates(r.terms, rows[previous].terms):
                        removed[previous] = i
                    elif dominates(rows[previous].terms, r.terms):
                        removed[i] = previous
                previous = i
        # Resolve chains. Cycles from duplicate/sweep dominations collapse to one
        # representative; every member then has the same coefficient vector.
        for i in list(removed):
            seen = [i]
            target = removed[i]
            while target in removed and target not in seen:
                seen.append(target)
                target = removed[target]
            if target in seen:
                cycle = seen[seen.index(target) :]
                rep = min(cycle)
                removed.pop(rep, None)
                for j in cycle:
                    if j != rep:
                        removed[j] = rep
                target = rep
            if i != target:
                removed[i] = target
        for i in list(removed):
            target = removed[i]
            while target in removed:
                target = removed[target]
            removed[i] = target
            if not dominates(rows[target].terms, rows[i].terms):
                raise ValueError("invalid resource-row dominance proof")
    cliques, witnesses = [], {}
    work, truncated = 0, False
    if config.conflict_cuts == "local_cliques":
        neighbors = defaultdict(set)
        # Round-robin over resources so one dense resource cannot consume every
        # candidate. This limits optional cuts only; baseline rows are complete.
        by_resource = defaultdict(list)
        for i, r in enumerate(rows):
            by_resource[r.resource].append(i)
        streams = {rid: iter(ids) for rid, ids in by_resource.items()}
        while streams and work < config.conflict_work_limit:
            for rid in list(streams):
                i = next(streams[rid], None)
                if i is None:
                    del streams[rid]
                    continue
                for a, b in combinations((k for k, c in rows[i].terms if c == 1), 2):
                    check(deadline)
                    if work >= config.conflict_work_limit:
                        break
                    work += 1
                    if (a, b) not in witnesses:
                        witnesses[a, b] = i
                        neighbors[a].add(b)
                        neighbors[b].add(a)
        truncated = bool(streams)
        existing = {tuple(k for k, c in r.terms) for r in rows}
        # A second bounded pass finds triangles whose pairwise witnesses span
        # different resources. Each candidate is valid even if it is redundant.
        examined = 0
        for a, b in sorted(witnesses):
            if (
                examined >= config.conflict_work_limit
                or len(cliques) >= config.conflict_cut_limit
            ):
                truncated = True
                break
            for c in sorted(neighbors[a]):
                examined += 1
                check(deadline)
                if examined > config.conflict_work_limit:
                    break
                if c <= b or c not in neighbors[b]:
                    continue
                triple = (a, b, c)
                proof = (witnesses[a, b], witnesses[a, c], witnesses[b, c])
                if len({rows[i].resource for i in proof}) < 2 or triple in existing:
                    continue
                if any(all(x in dict(rows[i].terms) for x in triple) for i in proof):
                    continue
                cliques.append((triple, proof))
                if len(cliques) >= config.conflict_cut_limit:
                    break
        work += examined
    data = dict(
        rows=tuple(rows),
        retained=tuple(i for i in range(len(rows)) if i not in removed),
        implied_by=tuple(sorted(removed.items())),
        cliques=tuple(cliques),
        pair_witnesses=tuple((pair, i) for pair, i in sorted(witnesses.items())),
        work=work,
        truncated=truncated,
    )
    fingerprint = stable_fingerprint(data | {"rows": tuple(asdict(r) for r in rows)})
    return PreparedResources(
        **data, fingerprint=fingerprint, seconds=perf_counter() - started
    )
