"""Bounded joint suffix repair; physical timing comes from canonical route options."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from .models import DddMovementProblem, DddRouteDecision
from .reference import (
    DddReferenceSolution,
    DddReferenceTrajectory,
    build_ddd_reference_visit,
)
from .reservation_calendar import DddReservationCalendar, visit_reservations
from .reservation_models import DddReservationInsertionConfig
from .reservation_waiting import DddReservationWaitWindowSolver
from .time_ticks import ddd_seconds_to_tick as tick
from .time_ticks import ddd_tick_to_seconds as seconds
from .trajectory_problem import DddTrajectoryWaitingPolicy


@dataclass
class DddReservationRepairResult:
    solution: DddReferenceSolution | None
    suffixes: dict[int, int]
    pair_checks: int
    labels: int
    reason: str


class DddReservationSuffixRepairer:
    def __init__(
        self,
        movement: DddMovementProblem,
        waiting_policy: DddTrajectoryWaitingPolicy,
        config: DddReservationInsertionConfig,
    ):
        self.movement, self.policy, self.config = movement, waiting_policy, config
        self.windows = DddReservationWaitWindowSolver(movement, waiting_policy)
        self.options = movement.route_options_by_state_id
        self.by_id = {o.id: o for o in movement.route_options}
        self.starts = {s.cabin_id: s for s in movement.starts}
        self.horizon_tick = movement.operational_end_tick
        self.resources = movement.resources_by_id

    def _open_at(self, trajectory, index):
        index = min(index, len(trajectory.visits) - 1)
        for i in range(index - 1, -1, -1):
            if trajectory.visits[i].decision is DddRouteDecision.STOP:
                return i
        return 0

    def repair(
        self,
        *,
        initial: DddReferenceSolution,
        calendar: DddReservationCalendar,
        candidate,
        protected_rides=(),
        deadline: float,
    ):
        trajectories = {t.cabin_id: t for t in initial.trajectories}
        suffixes = {
            candidate.cabin_id: self._open_at(
                trajectories[candidate.cabin_id], candidate.board_visit_index
            )
        }
        checks = labels = 0
        blockers = {}
        while len(suffixes) <= self.config.maximum_affected_cabins:
            orders = tuple(dict.fromkeys((tuple(suffixes), tuple(reversed(suffixes)))))
            for order in orders:
                if perf_counter() >= deadline:
                    return DddReservationRepairResult(
                        None, suffixes, checks, labels, "budget"
                    )
                with calendar.transaction(suffixes) as transaction:
                    replacements = {}
                    failed = False
                    for cabin in order:
                        forced = set()
                        if cabin == candidate.cabin_id:
                            forced.update(
                                (
                                    candidate.board_visit_index,
                                    candidate.alight_visit_index,
                                )
                            )
                        for q in protected_rides:
                            if (
                                q.cabin_id == cabin
                                and q.board_visit_index
                                < suffixes[cabin]
                                <= q.alight_visit_index
                            ):
                                forced.add(q.alight_visit_index)
                        path, found, nchecks, nlabels = self._path(
                            trajectories[cabin],
                            suffixes[cabin],
                            forced,
                            transaction,
                            deadline,
                        )
                        checks += nchecks
                        labels += nlabels
                        blockers.update((r.key, r) for r in found)
                        if path is None:
                            failed = True
                            break
                        replacements[cabin] = path
                        transaction.add_trajectory(self.movement, path, suffixes[cabin])
                    if not failed:
                        solution = DddReferenceSolution(
                            tuple(
                                replacements.get(t.cabin_id, t)
                                for t in initial.trajectories
                            )
                        )
                        return DddReservationRepairResult(
                            solution, suffixes, checks, labels, "repaired"
                        )
            # Reopen exactly a conflict-producing suffix, not an arbitrary cohort.
            available = [
                r
                for r in blockers.values()
                if not r.boundary_origin
                and r.cabin_id not in suffixes
                and r.cabin_id in trajectories
            ]
            if not available or len(suffixes) == self.config.maximum_affected_cabins:
                break
            blocker = min(
                available,
                key=lambda r: (
                    abs(r.visit_index - candidate.board_visit_index),
                    r.enter_tick,
                    r.key,
                ),
            )
            suffixes[blocker.cabin_id] = self._open_at(
                trajectories[blocker.cabin_id], blocker.visit_index
            )
        return DddReservationRepairResult(
            None, suffixes, checks, labels, "no feasible repair in bounded neighborhood"
        )

    def _path(self, original, first, forced, calendar, deadline):
        start = self.starts[original.cabin_id]
        prefix = original.visits[:first]
        entry = tick(prefix[-1].next_switch_time_seconds) if prefix else start.time_tick
        state = (
            self.by_id[prefix[-1].route_option_id].to_state_id
            if prefix
            else start.state_id
        )
        # Each label owns its new visits/reservations. Calendar retains the frozen prefix.
        beam = [(prefix, (), entry, state, 0)]
        blockers, checks, expanded = {}, 0, 0
        for index in range(first, start.max_visit_count):
            successors = []
            for visits, added, t, state, score in beam:
                if perf_counter() >= deadline:
                    return None, tuple(blockers.values()), checks, expanded
                if t > self.horizon_tick:
                    if not forced or index > max(forced):
                        return (
                            DddReferenceTrajectory(
                                original.cabin_id,
                                visits,
                                boundary_resource_occurrences=original.boundary_resource_occurrences,
                            ),
                            tuple(blockers.values()),
                            checks,
                            expanded,
                        )
                    continue
                old = original.visits[index] if index < len(original.visits) else None
                options = sorted(
                    self.options[state],
                    key=lambda o: (o.id != (old.route_option_id if old else ""), o.id),
                )
                if index in forced:
                    options = [
                        o for o in options if o.decision is DddRouteDecision.STOP
                    ]
                for option in options:
                    try:
                        windows = self.windows.solve(
                            option=option,
                            entry_tick=t,
                            calendar=calendar,
                            additional=added,
                            deadline=deadline,
                        )
                    except TimeoutError:
                        return None, tuple(blockers.values()), checks, expanded
                    checks += windows.pair_checks
                    blockers.update((r.key, r) for r in windows.blockers)
                    preferred = (
                        tick(old.wait_seconds)
                        if old and old.route_option_id == option.id
                        else 0
                    )
                    proposals = self._lookahead(
                        option, t, original, index, forced, calendar, preferred
                    )
                    waits = windows.candidates(
                        (preferred, *proposals, 0), self.config.wait_candidate_limit
                    )
                    for w in waits:
                        visit = build_ddd_reference_visit(
                            start=start,
                            visit_index=index,
                            switch_time_seconds=seconds(t),
                            option=option,
                            operational_end_seconds=self.movement.operational_end_seconds,
                            tolerance_seconds=1e-9,
                            wait_seconds=seconds(w),
                        )
                        next_tick = tick(visit.next_switch_time_seconds)
                        deviation = (
                            abs(next_tick - tick(old.next_switch_time_seconds))
                            if old
                            else w
                        )
                        successors.append(
                            (
                                visits + (visit,),
                                added
                                + visit_reservations(
                                    self.movement, visit, resources=self.resources
                                ),
                                next_tick,
                                option.to_state_id,
                                score + deviation,
                            )
                        )
                        expanded += 1
            if not successors:
                break
            # No earliest-arrival dominance is claimed: retain different timed paths.
            unique = {}
            for label in sorted(successors, key=lambda v: v[4]):
                signature = tuple(
                    (v.route_option_id, tick(v.wait_seconds)) for v in label[0][first:]
                )
                unique.setdefault(signature, label)
                if len(unique) >= self.config.beam_width:
                    break
            beam = list(unique.values())
        # A final visit may itself cross H at the certified visit bound.
        for visits, _, t, _, _ in beam:
            if t > self.horizon_tick and (not forced or len(visits) > max(forced)):
                return (
                    DddReferenceTrajectory(
                        original.cabin_id,
                        visits,
                        boundary_resource_occurrences=original.boundary_resource_occurrences,
                    ),
                    tuple(blockers.values()),
                    checks,
                    expanded,
                )
        return None, tuple(blockers.values()), checks, expanded

    def _lookahead(self, option, entry, original, index, forced, calendar, preferred):
        """Pull future reservation boundaries back to this legal exit (heuristic)."""
        if option.decision is DddRouteDecision.SKIP:
            return ()
        t, state = entry + option.duration_tick, option.to_state_id
        maximum = tick(self.policy.maximum_wait_seconds(option.station_id))
        values = set()
        for j in range(index + 1, index + 1 + self.config.lookahead_visits):
            options = self.options[state]
            old = original.visits[j] if j < len(original.visits) else None
            route = next(
                (o for o in options if old and o.id == old.route_option_id), options[0]
            )
            if j in forced:
                route = next(o for o in options if o.decision is DddRouteDecision.STOP)
            for usage in route.resource_usages:
                e, c = (
                    t + usage.follower_enter_offset_tick,
                    t + usage.leader_clear_offset_tick,
                )
                h = usage.separation_after_tick(
                    self.windows.resources[usage.resource_id].minimum_headway_tick
                )
                for r in calendar.for_resource(usage.resource_id):
                    for w in (
                        r.clear_tick + r.separation_tick - e,
                        r.enter_tick - c - h,
                    ):
                        if 0 <= w <= maximum:
                            values.add(w)
            if route.decision is DddRouteDecision.STOP:
                break
            t += route.duration_tick
            state = route.to_state_id
        return tuple(sorted(values, key=lambda w: (abs(w - preferred), w)))[
            : self.config.wait_candidate_limit
        ]
