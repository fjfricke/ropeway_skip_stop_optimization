"""Private, revisioned resource reservations for finite fixed-start trajectories."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from itertools import accumulate

from .models import DddMovementProblem
from .reference import DddReferenceSolution, DddReferenceTrajectory, DddReferenceVisit
from .time_ticks import ddd_seconds_to_tick


@dataclass(frozen=True, slots=True)
class DddReservation:
    resource_id: str
    cabin_id: int
    visit_index: int
    usage_index: int
    enter_tick: int
    clear_tick: int
    separation_tick: int
    boundary_origin: bool = False
    boundary_only: bool = False

    @property
    def key(self) -> tuple:
        return (
            self.cabin_id,
            self.visit_index,
            self.resource_id,
            self.usage_index,
            self.boundary_origin,
        )


def visit_reservations(
    problem: DddMovementProblem, visit: DddReferenceVisit, *, resources=None
) -> tuple[DddReservation, ...]:
    resources = problem.resources_by_id if resources is None else resources
    return tuple(
        _reservation(resources, o, i) for i, o in enumerate(visit.resource_occurrences)
    )


def _reservation(resources, occurrence, index):
    return DddReservation(
        occurrence.resource_id,
        occurrence.cabin_id,
        occurrence.visit_index,
        index,
        ddd_seconds_to_tick(occurrence.follower_enter_time_seconds),
        ddd_seconds_to_tick(occurrence.leader_clear_time_seconds),
        occurrence.separation_after_tick(resources[occurrence.resource_id]),
        occurrence.boundary_origin,
        occurrence.boundary_only,
    )


class DddReservationCalendar:
    def __init__(self, reservations: tuple[DddReservation, ...] = ()):
        self._revision = 0
        self._install(reservations)

    @classmethod
    def from_solution(cls, problem: DddMovementProblem, solution: DddReferenceSolution):
        entries = []
        resources = problem.resources_by_id
        for trajectory in solution.trajectories:
            entries.extend(
                _reservation(resources, o, i)
                for i, o in enumerate(trajectory.boundary_resource_occurrences)
            )
            for visit in trajectory.visits:
                entries.extend(visit_reservations(problem, visit, resources=resources))
        return cls(tuple(entries))

    def _install(self, reservations):
        if len({r.key for r in reservations}) != len(reservations):
            raise ValueError("duplicate reservation identity")
        self._entries = tuple(reservations)
        by_resource = {}
        for r in reservations:
            by_resource.setdefault(r.resource_id, []).append(r)
        self._by_resource = {
            k: tuple(sorted(v, key=lambda r: (r.enter_tick, r.key)))
            for k, v in by_resource.items()
        }

        self._entry_ticks = {
            k: tuple(r.enter_tick for r in rows)
            for k, rows in self._by_resource.items()
        }
        self._prefix_ends = {
            k: tuple(accumulate((r.clear_tick + r.separation_tick for r in rows), max))
            for k, rows in self._by_resource.items()
        }

    def overlapping(
        self,
        resource_id: str,
        minimum_enter_tick: int,
        maximum_clear_with_headway_tick: int,
    ):
        """Conservative pair candidates, including long earlier occupancies.

        A conflict requires fixed.enter < max(new.clear+headway) and
        fixed.clear+headway > min(new.enter). Prefix maxima prevent skipping
        a long-lived earlier reservation behind a short immediate predecessor.
        """
        rows = self.for_resource(resource_id)
        if not rows:
            return ()
        first = bisect_right(self._prefix_ends[resource_id], minimum_enter_tick)
        last = bisect_left(
            self._entry_ticks[resource_id], maximum_clear_with_headway_tick
        )
        return tuple(
            r
            for r in rows[first:last]
            if r.clear_tick + r.separation_tick > minimum_enter_tick
        )

    @property
    def revision(self):
        return self._revision

    @property
    def reservations(self):
        return self._entries

    def for_resource(self, resource_id):
        return self._by_resource.get(resource_id, ())

    def transaction(self, suffixes: dict[int, int]):
        return DddReservationTransaction(self, suffixes)


class DddReservationTransaction(DddReservationCalendar):
    def __init__(self, parent: DddReservationCalendar, suffixes: dict[int, int]):
        if any(v < 0 for v in suffixes.values()):
            raise ValueError("suffix indices must be nonnegative")
        self._parent = parent
        self._parent_revision = parent.revision
        self._closed = False
        super().__init__(
            tuple(
                r
                for r in parent.reservations
                if r.boundary_origin
                or r.cabin_id not in suffixes
                or r.visit_index < suffixes[r.cabin_id]
            )
        )

    def add_trajectory(
        self,
        problem: DddMovementProblem,
        trajectory: DddReferenceTrajectory,
        first_visit: int,
    ):
        if self._closed:
            raise RuntimeError("transaction is closed")
        additions = tuple(
            r
            for v in trajectory.visits[first_visit:]
            for r in visit_reservations(problem, v)
        )
        self._install(self.reservations + additions)

    def commit(self):
        """Caller must validate the complete candidate before publishing it."""
        if self._closed or self._parent.revision != self._parent_revision:
            raise RuntimeError("closed or stale reservation transaction")
        self._parent._install(self.reservations)
        self._parent._revision += 1
        self._closed = True

    def rollback(self):
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.rollback()
