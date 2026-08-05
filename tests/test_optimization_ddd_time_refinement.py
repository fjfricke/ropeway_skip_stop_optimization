from __future__ import annotations

from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.benchmarking.ddd_cases import (
    build_event_cell_bound_probe,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddCellFreeSupportRecovery,
    DddPartialTimeMaster,
    DddPartialTimeMasterStatus,
    DddPrimalRecoveryStatus,
    DddReferenceSolver,
    DddStrictTimeCellLifter,
    DddStrictTimeLiftStatus,
    DddTimeBoundaryError,
    DddTimeCell,
    DddTimeRefinementSolver,
    DddTimeRefinementStatus,
    validate_ddd_recovered_schedule,
)


def test_time_cells_are_half_open_at_refinement_boundary() -> None:
    lower = DddTimeCell("B", 5.0, 7.0)
    upper = DddTimeCell("B", 7.0, 10.0)

    assert not lower.contains(7.0, tolerance_seconds=1e-9)
    assert upper.contains(7.0, tolerance_seconds=1e-9)


def test_initial_partial_master_selects_optimistic_inconsistent_path() -> None:
    problem = build_event_cell_bound_probe()

    result = DddPartialTimeMaster().solve(problem)

    assert result.status is DddPartialTimeMasterStatus.OPTIMAL
    assert result.path is not None
    assert result.objective_lower_bound == pytest.approx(0.0)
    assert result.candidate_path_count == 4
    assert result.path.route_option_ids == (
        "route::A_stop_to_B",
        "route::B_continue_to_C",
    )
    assert result.path.terminal_cell.lower_seconds == pytest.approx(10.0)
    assert result.path.terminal_cell.upper_seconds == pytest.approx(12.0)


def test_strict_lift_refines_while_cell_free_recovery_finds_upper_bound() -> None:
    problem = build_event_cell_bound_probe()
    master = DddPartialTimeMaster().solve(problem)
    assert master.path is not None

    strict = DddStrictTimeCellLifter().lift(problem, master.path)
    recovery = DddCellFreeSupportRecovery().recover(problem, master.path)

    assert strict.status is DddStrictTimeLiftStatus.EVENT_CELL_INCONSISTENCY
    assert strict.schedule is None
    assert strict.inconsistency is not None
    assert strict.inconsistency.state_id == "B"
    assert strict.inconsistency.exact_source_time_seconds == pytest.approx(7.0)
    assert strict.inconsistency.required_source_upper_seconds == pytest.approx(7.0)
    assert strict.inconsistency.split_boundary_seconds == pytest.approx(7.0)
    assert recovery.status is DddPrimalRecoveryStatus.FEASIBLE
    assert recovery.schedule is not None
    assert recovery.schedule.terminal_time_seconds == pytest.approx(12.0)
    assert recovery.schedule.objective_value == pytest.approx(1.0)
    validate_ddd_recovered_schedule(problem, recovery.schedule)


def test_safe_split_rebuilds_partial_paths_and_raises_master_bound() -> None:
    problem = build_event_cell_bound_probe()
    refined = problem.with_discretization(
        problem.discretization.split(
            state_id="B",
            boundary_seconds=7.0,
            tolerance_seconds=1e-9,
        )
    )

    result = DddPartialTimeMaster().solve(refined)

    assert result.status is DddPartialTimeMasterStatus.OPTIMAL
    assert result.path is not None
    assert result.candidate_path_count == 2
    assert result.objective_lower_bound == pytest.approx(1.0)
    assert result.path.route_option_ids[0] == "route::A_stop_to_B"
    assert result.path.arcs[0].target_cell.lower_seconds == pytest.approx(7.0)
    assert result.path.terminal_cell.lower_seconds == pytest.approx(12.0)
    strict = DddStrictTimeCellLifter().lift(refined, result.path)
    assert strict.status is DddStrictTimeLiftStatus.FEASIBLE
    assert strict.schedule is not None
    assert strict.schedule.objective_value == pytest.approx(1.0)


def test_partial_master_keeps_route_departing_exactly_at_operational_horizon() -> None:
    problem = build_event_cell_bound_probe()
    movement = replace(
        problem.movement_problem,
        passenger_service_end_seconds=7.0,
        operational_end_seconds=7.0,
    )
    refined = replace(
        problem,
        movement_problem=movement,
        discretization=problem.discretization.split(
            state_id="B",
            boundary_seconds=7.0,
            tolerance_seconds=1e-9,
        ),
    )
    refined.validate()

    result = DddPartialTimeMaster().solve(refined)

    assert result.status is DddPartialTimeMasterStatus.OPTIMAL
    assert result.path is not None
    assert result.candidate_path_count == 2
    assert result.path.route_option_ids[0] == "route::A_stop_to_B"


def test_time_refinement_solver_closes_valid_lb_ub_gap_in_two_rounds() -> None:
    result = DddTimeRefinementSolver().solve(build_event_cell_bound_probe())

    assert result.status is DddTimeRefinementStatus.OPTIMAL
    assert result.solution is not None
    assert result.global_lower_bound == pytest.approx(1.0)
    assert result.global_upper_bound == pytest.approx(1.0)
    assert result.absolute_gap == pytest.approx(0.0)
    assert len(result.iterations) == 2
    first, second = result.iterations
    assert first.master_lower_bound == pytest.approx(0.0)
    assert first.global_upper_bound == pytest.approx(1.0)
    assert first.strict_lift_status is (
        DddStrictTimeLiftStatus.EVENT_CELL_INCONSISTENCY
    )
    assert first.split_state_id == "B"
    assert first.split_boundary_seconds == pytest.approx(7.0)
    assert second.master_lower_bound == pytest.approx(1.0)
    assert second.global_upper_bound == pytest.approx(1.0)
    assert second.strict_lift_status is DddStrictTimeLiftStatus.FEASIBLE
    assert result.final_discretization.partition("B").boundaries_seconds == (
        5.0,
        7.0,
        10.0,
    )


def test_iteration_limit_retains_valid_recovery_incumbent_and_open_gap() -> None:
    result = DddTimeRefinementSolver(max_iterations=1).solve(
        build_event_cell_bound_probe()
    )

    assert result.status is DddTimeRefinementStatus.FEASIBLE_WITH_GAP
    assert result.solution is not None
    assert result.global_lower_bound == pytest.approx(0.0)
    assert result.global_upper_bound == pytest.approx(1.0)
    assert result.absolute_gap == pytest.approx(1.0)
    assert result.final_discretization.partition("B").boundaries_seconds == (
        5.0,
        7.0,
        10.0,
    )


def test_duplicate_time_boundary_is_rejected() -> None:
    problem = build_event_cell_bound_probe()

    with pytest.raises(DddTimeBoundaryError, match="already exists"):
        problem.discretization.split(
            state_id="C",
            boundary_seconds=12.0,
            tolerance_seconds=1e-9,
        )


def test_exhaustive_exact_oracle_confirms_full_optimum_one() -> None:
    problem = build_event_cell_bound_probe()

    oracle = DddReferenceSolver(
        stop_after_first_feasible=False,
        max_retained_feasible_solutions=10,
    ).solve(problem.movement_problem)

    assert oracle.metrics.search_complete
    assert oracle.metrics.feasible_solution_count == 2
    exact_values = sorted(
        problem.objective.exact_value(
            solution.trajectories[0].support_signature,
            solution.trajectories[0].visits[-1].next_switch_time_seconds,
            tolerance_seconds=1e-9,
        )
        for solution in oracle.retained_solutions
    )
    assert exact_values == pytest.approx([1.0, 2.0])
