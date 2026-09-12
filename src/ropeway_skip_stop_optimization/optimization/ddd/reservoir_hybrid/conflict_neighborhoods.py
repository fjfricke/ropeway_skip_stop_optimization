"""Select joint repairs from conflicts of a concrete optimistic skip proposal.

Proposals are only selection heuristics. They are never accepted as timetables,
used to prune the feasible domain, or interpreted as guaranteed objective gains.
"""

from collections import defaultdict
from dataclasses import dataclass, replace
from bisect import bisect_left

from ..models import DddRouteDecision
from ..reservoir_cp_sat_certificate import validate_reservoir_cp_plan


@dataclass(frozen=True)
class TimedUse:
    resource: str
    enter: int
    clear: int
    cabin: int
    visit: int


def protected_uses(problem, trip):
    options = {o.id: o for o in problem.resolved_core.route_options}
    uses = []
    for i, (oid, start, wait) in enumerate(
        zip(trip.route_option_ids, trip.switch_ticks, trip.wait_ticks)
    ):
        o = options[oid]
        uses.append(
            TimedUse("state:" + o.from_state_id, start, start + 1, trip.cabin_id, i)
        )
        for u in o.resource_usages:
            r = problem.resolved_core.resources_by_id[u.resource_id]
            enter = (
                start
                + u.follower_enter_offset_tick
                + u.follower_enter_wait_coefficient * wait
            )
            clear = (
                start
                + u.leader_clear_offset_tick
                + u.leader_clear_wait_coefficient * wait
                + u.separation_after_tick(r.minimum_headway_tick)
            )
            if enter <= problem.resolved_core.operational_end_tick:
                uses.append(
                    TimedUse("resource:" + r.id, enter, clear, trip.cabin_id, i)
                )
    uses.append(
        TimedUse(
            "state:" + problem.entry_state_id,
            trip.return_tick,
            trip.return_tick + 1,
            trip.cabin_id,
            len(trip.route_option_ids),
        )
    )
    return tuple(uses)


def conflicts(proposal, calendar):
    by_resource = defaultdict(list)
    for u in calendar:
        by_resource[u.resource].append(u)
    for uses in by_resource.values():
        uses.sort(key=lambda u: u.enter)
    starts = {r: [u.enter for u in uses] for r, uses in by_resource.items()}
    found = []
    for u in proposal:
        others = by_resource[u.resource]
        for v in others[: bisect_left(starts.get(u.resource, []), u.clear)]:
            if u.cabin != v.cabin and v.clear > u.enter:
                found.append((u, v))
    return found


def select_conflict_neighborhoods(problem, plan, *, limit=4, max_open=6):
    validate_reservoir_cp_plan(problem, plan)
    options = {o.id: o for o in problem.resolved_core.route_options}
    rides = {r.id: r for r in problem.passenger_build.ride_candidates}
    through = defaultdict(int)
    for rid, n in plan.ride_counts.items():
        r = rides[rid]
        for i in range(r.board_visit_index + 1, r.alight_visit_index):
            through[r.cabin_id, i] += n
    calendar = tuple(u for t in plan.trips for u in protected_uses(problem, t))
    proposals = []
    oversized = 0
    for t in plan.trips:
        for i, oid in enumerate(t.route_option_ids):
            o = options[oid]
            if o.decision is not DddRouteDecision.STOP or not through[t.cabin_id, i]:
                continue
            for skip in problem.movement.route_options_by_state_id[o.from_state_id]:
                if skip.decision is not DddRouteDecision.SKIP:
                    continue
                saving = o.duration_tick + t.wait_ticks[i] - skip.duration_tick
                if saving <= 0:
                    continue
                ids = list(t.route_option_ids)
                ids[i] = skip.id
                waits = list(t.wait_ticks)
                waits[i] = 0
                proposal = replace(
                    t,
                    route_option_ids=tuple(ids),
                    wait_ticks=tuple(waits),
                    switch_ticks=tuple(
                        v - saving if j > i else v for j, v in enumerate(t.switch_ticks)
                    ),
                    return_tick=t.return_tick - saving,
                )
                edges = conflicts(protected_uses(problem, proposal), calendar)
                blockers = sorted({v.cabin for _, v in edges})
                if len(blockers) + 1 > max_open:
                    oversized += 1
                    continue
                potential = saving * through[t.cabin_id, i] / 1e6
                proposals.append(
                    dict(
                        anchor=t.cabin_id,
                        skip_visit=i,
                        skip_option=skip.id,
                        saving_seconds=saving / 1e6,
                        through_passengers=through[t.cabin_id, i],
                        optimistic_gain=potential,
                        open_ids=sorted([t.cabin_id, *blockers]),
                        blockers=blockers,
                        new_slots=1 if len(blockers) < 3 else 2,
                        conflicts=[
                            dict(
                                resource=u.resource,
                                anchor_visit=u.visit,
                                blocker=v.cabin,
                                blocker_visit=v.visit,
                                overlap_tick=min(u.clear, v.clear)
                                - max(u.enter, v.enter),
                            )
                            for u, v in edges
                        ],
                    )
                )
    proposals.sort(
        key=lambda x: (
            -x["optimistic_gain"] / len(x["open_ids"]),
            -x["optimistic_gain"],
            x["anchor"],
            x["skip_visit"],
        )
    )
    chosen = []
    seen = set()
    for p in proposals:
        key = tuple(p["open_ids"])
        if key in seen:
            continue
        seen.add(key)
        chosen.append(p)
        if len(chosen) == limit:
            break
    return dict(
        neighborhoods=chosen,
        candidate_proposals=len(proposals),
        oversized_proposals=oversized,
        note="Optimistic selection only; all actual route and timing decisions remain free in repair.",
    )
