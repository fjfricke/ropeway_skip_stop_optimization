"""Exact integer cost identity and optimistic endpoint quadrature."""

from bisect import bisect_right
from dataclasses import dataclass

from ..time_ticks import ddd_seconds_to_tick as tick
from ..reservoir_cp_sat_certificate import validate_reservoir_cp_plan


@dataclass(frozen=True)
class ArrivalIntervalPartition:
    points: tuple[int, ...]

    def __post_init__(self):
        if len(self.points) < 2 or any(type(x) is not int for x in self.points):
            raise ValueError("partition needs integer tick boundaries")
        if self.points[0] < 0 or any(
            a >= b for a, b in zip(self.points, self.points[1:])
        ):
            raise ValueError("partition boundaries must strictly increase")

    @classmethod
    def build(cls, problem, step_tick):
        if type(step_tick) is not int or step_tick <= 0:
            raise ValueError("positive integer partition step required")
        end = problem.resolved_core.operational_end_tick
        return cls(
            tuple(
                sorted(
                    {
                        0,
                        end,
                        end + 1,
                        problem.resolved_core.passenger_service_end_tick,
                        *(tick(g.release_time_seconds) for g in problem.demand_groups),
                        *range(0, end, step_tick),
                    }
                )
            )
        )

    def cell(self, t):
        i = bisect_right(self.points, t) - 1
        if i < 0 or i >= len(self.points) - 1:
            raise ValueError("time outside partition")
        return i

    def floor(self, t):
        return self.points[self.cell(t)]

    def bounds(self, i):
        return self.points[i], self.points[i + 1] - 1

    def refine(self, points):
        if any(
            type(x) is not int or not self.points[0] < x < self.points[-1]
            for x in points
        ):
            raise ValueError("invalid refinement point")
        return type(self)(tuple(sorted(set(self.points).union(points))))


def arrivals(problem, plan):
    validate_reservoir_cp_plan(problem, plan)
    trips = {t.cabin_id: t for t in plan.trips}
    options = {o.id: o for o in problem.resolved_core.route_options}
    rides = {r.id: r for r in problem.passenger_build.ride_candidates}
    result = {g.id: [] for g in problem.demand_groups}
    for rid, n in plan.ride_counts.items():
        r = rides[rid]
        trip = trips[r.cabin_id]
        i = r.alight_visit_index
        t = trip.switch_ticks[i] + tick(
            options[trip.route_option_ids[i]].platform_entry_offset_seconds
        )
        result[r.demand_group_id].append((t, n))
    return {g: tuple(sorted(v)) for g, v in result.items()}


class ArrivalCurveEvaluator:
    def evaluate(self, problem, plan, partition):
        metrics = validate_reservoir_cp_plan(problem, plan)
        events = arrivals(problem, plan)
        horizon = problem.resolved_core.passenger_service_end_tick
        exact = optimistic = 0
        for g in problem.demand_groups:
            release = tick(g.release_time_seconds)
            if release not in partition.points or horizon not in partition.points:
                raise ValueError(
                    "release and service horizon must be partition boundaries"
                )
            outstanding, previous = g.count, release
            for t, n in events[g.id]:
                exact += outstanding * (t - previous)
                outstanding -= n
                previous = t
            exact += outstanding * (horizon - previous)
            for a, b in zip(partition.points, partition.points[1:]):
                if release <= a < horizon:
                    delivered = sum(n for t, n in events[g.id] if t < b)
                    optimistic += (b - a) * (g.count - delivered)
        if exact != metrics.journey_time_tick or optimistic > exact:
            raise ValueError("arrival-curve certificate mismatch")
        return {
            "exact_tick_cost": exact,
            "interval_tick_cost": optimistic,
            "served": metrics.served,
            "unserved": metrics.unserved,
        }
