"""Passenger intentions and integer fixed-movement repair using shared EAN rides."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from ..ean.optimizers.fixed_movement_passenger_model import (
    build_ean_fixed_movement_rides,
)
from ..ean.passenger_plan import EanPassengerServicePlan, EanServedRideGroup
from .reservation_models import DddServiceInsertionIntent


class DddServiceInsertionCandidateBuilder:
    def build(self, problem, initial_plan, *, limit=100, group_limit=3):
        visits = {
            (v.cabin_id, v.visit_index): v
            for t in initial_plan.solution.trajectories
            for v in t.visits
        }
        groups = sorted(
            problem.passenger_build.demand_groups,
            key=lambda g: (-initial_plan.unserved_counts[g.id], g.id),
        )[:group_limit]
        queues = []
        for group in groups:
            candidates = [
                q
                for q in problem.passenger_build.ride_candidates
                if q.demand_group_id == group.id
                and (q.cabin_id, q.board_visit_index) in visits
                and (q.cabin_id, q.alight_visit_index) in visits
                and any(
                    visits[q.cabin_id, i].decision.value == "skip"
                    for i in (q.board_visit_index, q.alight_visit_index)
                )
            ]
            candidates.sort(
                key=lambda q: (
                    visits[q.cabin_id, q.alight_visit_index].switch_time_seconds,
                    q.cabin_id,
                    q.board_visit_index,
                    q.id,
                )
            )
            # Round-robin over groups; candidates cover early opportunities on many cabins.
            queue = deque()
            for q in candidates:
                for count in dict.fromkeys(
                    (1, min(problem.artifact.config.cabin_capacity, group.count))
                ):
                    if count:
                        queue.append(DddServiceInsertionIntent(q.id, count))
            queues.append(queue)
        result = []
        while any(queues) and len(result) < limit:
            for queue in queues:
                if queue and len(result) < limit:
                    result.append(queue.popleft())
        return tuple(result)


@dataclass(frozen=True, slots=True)
class DddReservationPassengerResult:
    ride_counts: dict[str, int]
    passenger_plan: EanPassengerServicePlan


class DddReservationPassengerEvaluator:
    def evaluate(self, *, problem, movement_plan, initial_plan, intent, suffixes):
        rides = build_ean_fixed_movement_rides(
            passenger_build=problem.passenger_build,
            movement_plan=movement_plan,
            horizon_seconds=problem.artifact.config.horizon_seconds,
        )
        by_id = {r.candidate.id: r for r in rides}
        groups = {g.id: g for g in problem.passenger_build.demand_groups}
        candidates = {q.id: q for q in problem.passenger_build.ride_candidates}
        remaining = {g.id: g.count for g in groups.values()}
        loads, counts = defaultdict(int), defaultdict(int)
        capacity = problem.artifact.config.cabin_capacity

        def assign(qid, count):
            if qid not in by_id:
                return 0
            q = by_id[qid].candidate
            amount = min(
                count,
                remaining[q.demand_group_id],
                *(
                    capacity - loads[q.cabin_id, v]
                    for v in range(q.board_visit_index, q.alight_visit_index)
                ),
            )
            if amount > 0:
                counts[qid] += amount
                remaining[q.demand_group_id] -= amount
                for v in range(q.board_visit_index, q.alight_visit_index):
                    loads[q.cabin_id, v] += amount
            return amount

        # Preserve commitments made in frozen prefixes, including their destination.
        for qid, count in initial_plan.ride_counts.items():
            q = candidates[qid]
            if q.cabin_id not in suffixes or q.board_visit_index < suffixes[q.cabin_id]:
                if assign(qid, count) != count:
                    return None
        already = counts[intent.candidate_id]
        if (
            assign(intent.candidate_id, max(0, intent.count - already)) + already
            < intent.count
        ):
            return None
        for qid, count in initial_plan.ride_counts.items():
            assign(qid, max(0, count - counts[qid]))
        for ride in sorted(
            rides, key=lambda r: (r.alighting_time_seconds, r.candidate.id)
        ):
            assign(ride.candidate.id, remaining[ride.candidate.demand_group_id])
        counts = {qid: n for qid, n in counts.items() if n > 0}
        services = tuple(
            EanServedRideGroup(
                by_id[qid].candidate.demand_group_id,
                by_id[qid].candidate.cabin_id,
                by_id[qid].candidate.board_visit_index,
                by_id[qid].candidate.alight_visit_index,
                n,
                by_id[qid].boarding_time_seconds,
                by_id[qid].alighting_time_seconds,
            )
            for qid, n in sorted(counts.items())
        )
        return DddReservationPassengerResult(
            counts,
            EanPassengerServicePlan(
                problem.artifact.scenario_id,
                problem.artifact.config.horizon_seconds,
                services,
                remaining,
            ),
        )
