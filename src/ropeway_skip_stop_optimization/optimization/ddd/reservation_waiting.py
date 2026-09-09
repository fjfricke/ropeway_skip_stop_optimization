"""Exact local integer wait intervals; no wait-grid enumeration or solver model."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from .models import DddMovementProblem, DddRouteDecision, DddRouteOption
from .reservation_calendar import DddReservation, DddReservationCalendar
from .resource_time import DddTickInterval
from .time_ticks import ddd_seconds_to_tick
from .trajectory_problem import DddTrajectoryWaitingPolicy


@dataclass(frozen=True, slots=True)
class DddWaitWindowResult:
    intervals: tuple[DddTickInterval, ...]
    step_tick: int
    blockers: tuple[DddReservation, ...]
    pair_checks: int

    def contains(self, tick: int) -> bool:
        return tick % self.step_tick == 0 and any(
            i.contains_tick(tick) for i in self.intervals
        )

    def candidates(
        self, preferred: tuple[int, ...] = (), limit: int = 12
    ) -> tuple[int, ...]:
        values = []
        for w in preferred:
            for interval in self.intervals:
                lo = (
                    (interval.lower_tick + self.step_tick - 1) // self.step_tick
                ) * self.step_tick
                hi = (interval.last_tick // self.step_tick) * self.step_tick
                if lo <= hi:
                    values.append(
                        max(lo, min(hi, (w // self.step_tick) * self.step_tick))
                    )
        for interval in self.intervals:
            lo = (
                (interval.lower_tick + self.step_tick - 1) // self.step_tick
            ) * self.step_tick
            hi = (interval.last_tick // self.step_tick) * self.step_tick
            if lo <= hi:
                values.extend((lo, hi))
        return tuple(dict.fromkeys(values))[:limit]


class DddReservationWaitWindowSolver:
    def __init__(
        self, problem: DddMovementProblem, waiting_policy: DddTrajectoryWaitingPolicy
    ):
        self.problem = problem
        self.policy = waiting_policy
        self.resources = problem.resources_by_id
        self.horizon_tick = problem.operational_end_tick

    def solve(
        self,
        *,
        option: DddRouteOption,
        entry_tick: int,
        calendar: DddReservationCalendar,
        additional: tuple[DddReservation, ...] = (),
        deadline: float = float("inf"),
    ) -> DddWaitWindowResult:
        maximum = ddd_seconds_to_tick(
            self.policy.maximum_wait_seconds(option.station_id)
        )
        if (
            option.decision is DddRouteDecision.SKIP
            or self.policy.step_seconds is None
            or option.platform_exit_offset_seconds is None
            or entry_tick + ddd_seconds_to_tick(option.platform_exit_offset_seconds)
            < ddd_seconds_to_tick(self.policy.earliest_wait_time_seconds)
        ):
            maximum = 0
        step = max(1, ddd_seconds_to_tick(self.policy.step_seconds or 0))
        forbidden, blockers = [], {}
        checks = 0
        for usage in option.resource_usages:
            e = entry_tick + usage.follower_enter_offset_tick
            c = entry_tick + usage.leader_clear_offset_tick
            a, b = (
                usage.follower_enter_wait_coefficient,
                usage.leader_clear_wait_coefficient,
            )
            h = usage.separation_after_tick(
                self.resources[usage.resource_id].minimum_headway_tick
            )
            if e > self.horizon_tick:
                continue
            active_maximum = min(maximum, self.horizon_tick - e) if a else maximum
            max_clear = c + b * active_maximum + h
            partners = (
                *calendar.overlapping(usage.resource_id, e, max_clear),
                *(
                    r
                    for r in additional
                    if r.resource_id == usage.resource_id
                    and r.enter_tick < max_clear
                    and r.clear_tick + r.separation_tick > e
                ),
            )
            for r in partners:
                checks += 1
                if checks % 256 == 0 and perf_counter() >= deadline:
                    raise TimeoutError("wait-window deadline")
                if r.boundary_only and not r.boundary_origin:
                    continue
                lo, hi = 0, maximum
                # c+b*w+h > r.enter AND e+a*w < r.clear+r.h AND active(e+a*w).
                if b:
                    lo = max(lo, r.enter_tick + 1 - c - h)
                elif c + h <= r.enter_tick:
                    continue
                upper = min(
                    r.clear_tick + r.separation_tick - 1,
                    self.horizon_tick,
                )
                if a:
                    hi = min(hi, upper - e)
                elif e > upper:
                    continue
                if lo <= hi:
                    forbidden.append((lo, hi + 1))
                    blockers[r.key] = r
        intervals, cursor = [], 0
        for lo, hi in sorted(forbidden):
            if lo > cursor:
                intervals.append(DddTickInterval(cursor, lo))
            cursor = max(cursor, hi)
        if cursor <= maximum:
            intervals.append(DddTickInterval(cursor, maximum + 1))
        intervals = tuple(
            i
            for i in intervals
            if ((i.lower_tick + step - 1) // step) * step < i.upper_tick
        )
        return DddWaitWindowResult(intervals, step, tuple(blockers.values()), checks)
