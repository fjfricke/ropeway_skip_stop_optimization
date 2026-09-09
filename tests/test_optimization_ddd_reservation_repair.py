from time import perf_counter

from test_optimization_ddd_cp_sat_integrated import tiny_problem
from test_optimization_ddd_reservation_insertion import skip_seed

from ropeway_skip_stop_optimization.optimization.ddd.fixed_k_certificate import (
    DddFixedKPrimalValidator,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservation_calendar import (
    DddReservation,
    DddReservationCalendar,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservation_models import (
    DddReservationInsertionConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservation_repair import (
    DddReservationSuffixRepairer,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_seconds_to_tick as tick,
)


def test_blocker_expansion_repairs_case_impossible_for_single_cabin(monkeypatch):
    _, p = tiny_problem(horizon=100, starts=(0, 20), maximum_wait=0)
    seed = skip_seed(p)
    movement = p.resolved_trajectory_problem.structural_movement_problem
    calendar = DddReservationCalendar.from_solution(movement, seed.solution)
    entries = calendar.reservations
    q = next(
        q
        for q in p.passenger_build.ride_candidates
        if q.id == "ride::ab::cabin_0::board_0::alight_1"
    )
    import gurobipy
    from ortools.sat.python import cp_model

    monkeypatch.setattr(
        gurobipy,
        "Model",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("MIP in repair")),
    )
    monkeypatch.setattr(
        cp_model.CpSolver,
        "solve",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("CP in repair")),
    )

    def run(size):
        return DddReservationSuffixRepairer(
            movement,
            p.resolved_trajectory_problem.waiting_policy,
            DddReservationInsertionConfig(maximum_affected_cabins=size),
        ).repair(
            initial=seed.solution,
            calendar=calendar,
            candidate=q,
            deadline=perf_counter() + 3,
        )

    assert run(1).solution is None
    result = run(2)
    assert result.solution is not None and len(result.suffixes) == 2
    valid = DddFixedKPrimalValidator().validate(
        p, result.solution, {q.id: 1}, provenance="two-cabin"
    )
    assert valid.objective < seed.objective
    assert calendar.reservations == entries


def test_future_nonwaitable_entry_moves_wait_to_previous_exit():
    _, p = tiny_problem(horizon=130, maximum_wait=20, waiting_step=1e-6)
    seed = skip_seed(p)
    m = p.resolved_trajectory_problem.structural_movement_problem
    a = next(
        o
        for o in m.route_options_by_state_id[m.starts[0].state_id]
        if o.decision.value == "stop"
    )
    b = next(
        o
        for o in m.route_options_by_state_id[a.to_state_id]
        if o.decision.value == "stop"
    )
    usage = next(u for u in b.resource_usages if u.follower_enter_wait_coefficient == 0)
    entry = a.duration_tick + usage.follower_enter_offset_tick
    blocker = DddReservation(
        usage.resource_id, 99, 0, 0, entry, entry + 2_000_000, 1_000_000
    )
    cal = DddReservationCalendar((blocker,))
    repair = DddReservationSuffixRepairer(
        m, p.resolved_trajectory_problem.waiting_policy, DddReservationInsertionConfig()
    )
    path, _, _, _ = repair._path(
        seed.solution.trajectories[0], 0, {0, 1}, cal, perf_counter() + 3
    )
    assert path is not None
    assert path.visits[0].wait_seconds >= 3
    occurrence = next(
        o
        for o in path.visits[1].resource_occurrences
        if o.resource_id == usage.resource_id
    )
    assert (
        tick(occurrence.follower_enter_time_seconds)
        >= blocker.clear_tick + blocker.separation_tick
    )
