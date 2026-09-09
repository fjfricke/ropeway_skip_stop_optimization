from dataclasses import replace
from itertools import product
from random import Random

import pytest
from test_optimization_ddd_cp_sat_integrated import tiny_problem

from ropeway_skip_stop_optimization.optimization.ddd.models import DddResourceUsage
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceResourceOccurrence,
    build_ddd_reference_visit,
    find_ddd_reference_conflicts,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservation_calendar import (
    DddReservation,
    DddReservationCalendar,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservation_waiting import (
    DddReservationWaitWindowSolver,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_tick_to_seconds as sec,
)


@pytest.mark.parametrize("a,b,step", list(product((0, 1), (0, 1), (1, 2))))
def test_wait_intervals_equal_exhaustive_reference_pairs(a, b, step):
    _, p = tiny_problem(maximum_wait=8e-6, waiting_step=step * 1e-6)
    m = replace(
        p.resolved_trajectory_problem.structural_movement_problem,
        operational_end_seconds=sec(16),
    )
    policy = p.resolved_trajectory_problem.waiting_policy
    original = next(o for o in m.route_options if o.decision.value == "stop")
    resource = m.resources[0]
    usage = DddResourceUsage(
        resource.id,
        sec(13),
        sec(12),
        separation_after_seconds=sec(3),
        leader_clear_wait_coefficient=b,
        follower_enter_wait_coefficient=a,
    )
    option = replace(original, resource_usages=(usage,))
    rng = Random(49)
    for trial in range(50):
        reservations = tuple(
            DddReservation(
                resource.id,
                i + 1,
                0,
                0,
                rng.randint(0, 20),
                rng.randint(20, 25),
                rng.randint(1, 5),
                boundary_origin=bool(i % 2),
            )
            for i in range(3)
        )
        result = DddReservationWaitWindowSolver(m, policy).solve(
            option=option, entry_tick=0, calendar=DddReservationCalendar(reservations)
        )
        for w in range(9):
            visit = build_ddd_reference_visit(
                start=m.starts[0],
                visit_index=0,
                switch_time_seconds=0,
                option=option,
                operational_end_seconds=m.operational_end_seconds,
                tolerance_seconds=1e-9,
                wait_seconds=sec(w),
            )
            conflicts = []
            for current in visit.resource_occurrences:
                for r in reservations:
                    fixed = DddReferenceResourceOccurrence(
                        r.resource_id,
                        r.cabin_id,
                        0,
                        sec(r.clear_tick),
                        sec(r.enter_tick),
                        sec(r.separation_tick),
                        boundary_origin=r.boundary_origin,
                    )
                    conflicts.extend(find_ddd_reference_conflicts((current, fixed), m))
            assert result.contains(w) == (w % step == 0 and not conflicts)
        assert all(result.contains(w) for w in result.candidates((0, 4, 8)))


def test_no_wait_skip_earliest_boundary_and_billion_tick_grid(monkeypatch):
    _, p = tiny_problem(maximum_wait=1200, waiting_step=1e-6)
    m = p.resolved_trajectory_problem.structural_movement_problem
    policy = p.resolved_trajectory_problem.waiting_policy
    monkeypatch.setattr(
        type(policy),
        "wait_values_seconds",
        lambda *a: pytest.fail("enumerated waiting grid"),
    )
    stop = next(o for o in m.route_options if o.decision.value == "stop")
    skip = next(o for o in m.route_options if o.decision.value == "skip")
    solver = DddReservationWaitWindowSolver(m, policy)
    result = solver.solve(option=stop, entry_tick=0, calendar=DddReservationCalendar())
    assert result.intervals[0].upper_tick == 1_200_000_001
    assert solver.solve(
        option=skip, entry_tick=0, calendar=DddReservationCalendar()
    ).candidates() == (0,)
    blocked = DddReservationWaitWindowSolver(
        m, replace(policy, earliest_wait_time_seconds=100)
    )
    assert blocked.solve(
        option=stop, entry_tick=0, calendar=DddReservationCalendar()
    ).candidates() == (0,)


def test_calendar_transactions_keep_boundary_and_rollback_on_exception():
    entries = (
        DddReservation("r", 0, 0, 0, 0, 3, 1),
        DddReservation("r", 0, 0, 0, -2, 0, 1, True),
    )
    calendar = DddReservationCalendar(entries)
    with pytest.raises(RuntimeError, match="test"):
        with calendar.transaction({0: 0}) as tx:
            assert tx.reservations == (entries[1],)
            raise RuntimeError("test")
    assert calendar.reservations == entries and calendar.revision == 0
    stale = calendar.transaction({})
    with calendar.transaction({}) as tx:
        tx.commit()
    with pytest.raises(RuntimeError, match="stale"):
        stale.commit()
    assert calendar.reservations == entries


def test_overlap_index_keeps_long_earlier_occupancies():
    rows = (
        DddReservation("r", 0, 0, 0, 0, 100, 4),
        DddReservation("r", 1, 0, 0, 20, 25, 1),
        DddReservation("r", 2, 0, 0, 50, 60, 2),
        DddReservation("r", 3, 0, 0, 90, 91, 1),
    )
    cal = DddReservationCalendar(rows)
    assert cal.overlapping("r", 80, 85) == (rows[0],)
    assert cal.overlapping("r", 104, 105) == ()
    assert cal.overlapping("r", 26, 50) == (rows[0],)


def test_pruned_and_full_calendars_return_identical_wait_domains():
    class FullCalendar(DddReservationCalendar):
        def overlapping(self, resource_id, *args):
            return self.for_resource(resource_id)

    _, p = tiny_problem(maximum_wait=12, waiting_step=1)
    m = p.resolved_trajectory_problem.structural_movement_problem
    solver = DddReservationWaitWindowSolver(
        m, p.resolved_trajectory_problem.waiting_policy
    )
    rng = Random(712)
    for trial in range(50):
        rows = tuple(
            DddReservation(
                r.id,
                i,
                0,
                0,
                t,
                t + rng.randint(0, 50_000_000),
                rng.randint(1, 7_000_000),
            )
            for i, (r, t) in enumerate(
                (rng.choice(m.resources), rng.randint(-10_000_000, 150_000_000))
                for _ in range(80)
            )
        )
        fast, full = DddReservationCalendar(rows), FullCalendar(rows)
        option = rng.choice(m.route_options)
        entry = rng.randint(0, 140_000_000)
        a = solver.solve(option=option, entry_tick=entry, calendar=fast)
        b = solver.solve(option=option, entry_tick=entry, calendar=full)
        assert a.intervals == b.intervals
        assert {r.key for r in a.blockers} == {r.key for r in b.blockers}
