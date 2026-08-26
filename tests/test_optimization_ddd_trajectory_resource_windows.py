import pytest

from ropeway_skip_stop_optimization.optimization.ddd import (
    DddFixedStart,
    DddMovementProblem,
    DddMovementState,
    DddReferenceResourceOccurrence,
    DddReferenceTrajectory,
    DddReferenceVisit,
    DddResource,
    DddRouteDecision,
    DddRouteOption,
    DddTrajectoryFactorizedLpOptimizer,
    DddTrajectoryPassengerMasterProblem,
    DddTrajectoryPassengerOption,
    DddTrajectoryPassengerRide,
    DddTrajectoryResourceWindow,
    DddTrajectoryResourceWindowPricingTerm,
    DddTrajectoryResourceWindowRow,
    build_ddd_trajectory_resource_window_row,
    ddd_trajectory_pair_has_resource_window_witness,
    ddd_trajectory_resource_intervals,
    find_ddd_reference_conflicts,
    separate_ddd_trajectory_resource_windows,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_seconds_to_tick,
)


def _movement_problem(*, headway_seconds: float = 1.0) -> DddMovementProblem:
    return DddMovementProblem(
        scenario_id="resource-window-test",
        passenger_service_end_seconds=10.0,
        operational_end_seconds=10.0,
        states=(DddMovementState("s"),),
        starts=(
            DddFixedStart(0, "s", 0.0, 1),
            DddFixedStart(1, "s", 0.0, 1),
        ),
        route_options=(
            DddRouteOption(
                id="loop",
                from_state_id="s",
                to_state_id="s",
                station_id="station",
                decision=DddRouteDecision.SKIP,
                duration_seconds=11.0,
                platform_entry_offset_seconds=None,
                platform_exit_offset_seconds=None,
                exit_switch_offset_seconds=11.0,
                resource_usages=(),
            ),
        ),
        resources=(DddResource("merge", headway_seconds),),
    )


def _trajectory(
    cabin_id: int,
    *,
    enter_seconds: float,
    clear_seconds: float,
) -> DddReferenceTrajectory:
    occurrence = DddReferenceResourceOccurrence(
        resource_id="merge",
        cabin_id=cabin_id,
        visit_index=0,
        leader_clear_time_seconds=clear_seconds,
        follower_enter_time_seconds=enter_seconds,
    )
    return DddReferenceTrajectory(
        cabin_id=cabin_id,
        visits=(
            DddReferenceVisit(
                cabin_id=cabin_id,
                visit_index=0,
                state_id="s",
                route_option_id="loop",
                decision=DddRouteDecision.SKIP,
                switch_time_seconds=0.0,
                next_switch_time_seconds=11.0,
                resource_occurrences=(occurrence,),
            ),
        ),
    )


def test_protected_interval_uses_half_open_headway_boundary() -> None:
    problem = _movement_problem(headway_seconds=1.0)
    trajectory = _trajectory(0, enter_seconds=1.0, clear_seconds=2.0)

    interval = ddd_trajectory_resource_intervals(trajectory, problem)[0]

    assert interval.enter_tick == ddd_seconds_to_tick(1.0)
    assert interval.clear_with_headway_tick == ddd_seconds_to_tick(3.0)
    assert interval.contains(ddd_seconds_to_tick(1.0))
    assert interval.contains(ddd_seconds_to_tick(2.999))
    assert not interval.contains(ddd_seconds_to_tick(3.0))


def test_boundary_interval_is_clipped_to_the_optimization_horizon() -> None:
    problem = _movement_problem(headway_seconds=1.0)
    boundary = DddReferenceResourceOccurrence(
        resource_id="merge",
        cabin_id=0,
        visit_index=0,
        leader_clear_time_seconds=0.5,
        follower_enter_time_seconds=-2.0,
        boundary_origin=True,
    )
    trajectory = DddReferenceTrajectory(
        cabin_id=0,
        visits=(),
        boundary_resource_occurrences=(boundary,),
    )

    interval = ddd_trajectory_resource_intervals(trajectory, problem)[0]

    assert interval.enter_tick == 0
    assert interval.clear_with_headway_tick == ddd_seconds_to_tick(1.5)
    assert interval.contains(0)


def test_negative_non_boundary_interval_is_rejected() -> None:
    problem = _movement_problem(headway_seconds=1.0)
    occurrence = DddReferenceResourceOccurrence(
        resource_id="merge",
        cabin_id=0,
        visit_index=0,
        leader_clear_time_seconds=0.5,
        follower_enter_time_seconds=-2.0,
    )
    trajectory = DddReferenceTrajectory(
        cabin_id=0,
        visits=(),
        boundary_resource_occurrences=(occurrence,),
    )

    with pytest.raises(ValueError, match="non-boundary"):
        ddd_trajectory_resource_intervals(trajectory, problem)


def test_resource_window_pricing_term_uses_minimization_dual_sign() -> None:
    window = DddTrajectoryResourceWindow("merge", 1)

    assert DddTrajectoryResourceWindowPricingTerm(
        window=window,
        raw_dual=-7.0,
    ).congestion_penalty == pytest.approx(7.0)
    with pytest.raises(ValueError, match="invalid sign"):
        DddTrajectoryResourceWindowPricingTerm(
            window=window,
            raw_dual=1.0,
        ).validate()


def test_sweep_processes_exit_before_entry_at_equal_tick() -> None:
    problem = _movement_problem(headway_seconds=1.0)
    trajectories = {
        "first": _trajectory(0, enter_seconds=0.0, clear_seconds=0.0),
        "second": _trajectory(1, enter_seconds=1.0, clear_seconds=1.0),
    }

    separated = separate_ddd_trajectory_resource_windows(
        movement_problem=problem,
        trajectory_by_option_id=trajectories,
        option_values_by_id={"first": 1.0, "second": 1.0},
    )

    assert separated.new_windows == ()
    assert separated.maximum_violation == pytest.approx(0.0)


def test_sweep_finds_fractional_clique_and_builds_all_coefficients() -> None:
    problem = _movement_problem(headway_seconds=1.0)
    trajectories = {
        "first": _trajectory(0, enter_seconds=0.0, clear_seconds=1.0),
        "second": _trajectory(1, enter_seconds=1.0, clear_seconds=2.0),
    }

    separated = separate_ddd_trajectory_resource_windows(
        movement_problem=problem,
        trajectory_by_option_id=trajectories,
        option_values_by_id={"first": 0.6, "second": 0.6},
    )

    assert len(separated.new_windows) == 1
    assert separated.maximum_violation == pytest.approx(0.2)
    window = separated.new_windows[0]
    assert window.anchor_tick == ddd_seconds_to_tick(1.0)
    row = build_ddd_trajectory_resource_window_row(
        window=window,
        movement_problem=problem,
        trajectory_by_option_id=trajectories,
    )
    assert row.coefficients == (("first", 1), ("second", 1))

    repeated = separate_ddd_trajectory_resource_windows(
        movement_problem=problem,
        trajectory_by_option_id=trajectories,
        option_values_by_id={"first": 0.6, "second": 0.6},
        existing_windows=(window,),
    )
    assert repeated.violating_window_count == 1
    assert repeated.new_windows == ()


@pytest.mark.parametrize(
    "second_enter, expected_conflict",
    ((0.999, True), (1.0, False)),
)
def test_resource_window_witness_matches_pair_conflict_boundary(
    second_enter: float,
    expected_conflict: bool,
) -> None:
    problem = _movement_problem(headway_seconds=1.0)
    first = _trajectory(0, enter_seconds=0.0, clear_seconds=0.0)
    second = _trajectory(
        1,
        enter_seconds=second_enter,
        clear_seconds=second_enter,
    )

    conflicts = find_ddd_reference_conflicts(
        (*first.resource_occurrences, *second.resource_occurrences),
        problem,
    )

    assert bool(conflicts) is expected_conflict
    assert (
        ddd_trajectory_pair_has_resource_window_witness(
            first=first,
            second=second,
            movement_problem=problem,
        )
        is expected_conflict
    )


def test_asymmetric_unpriceable_conflict_is_left_to_pair_fallback() -> None:
    problem = _movement_problem(headway_seconds=1.0)
    first = _trajectory(0, enter_seconds=10.0, clear_seconds=0.0)
    second = _trajectory(1, enter_seconds=0.0, clear_seconds=10.0)

    conflicts = find_ddd_reference_conflicts(
        (*first.resource_occurrences, *second.resource_occurrences),
        problem,
    )
    separated = separate_ddd_trajectory_resource_windows(
        movement_problem=problem,
        trajectory_by_option_id={"first": first, "second": second},
        option_values_by_id={"first": 1.0, "second": 1.0},
    )

    assert conflicts
    assert not ddd_trajectory_pair_has_resource_window_witness(
        first=first,
        second=second,
        movement_problem=problem,
    )
    assert separated.new_windows == ()


def test_resource_clique_strictly_strengthens_pair_lp() -> None:
    pytest.importorskip("gurobipy")
    options = tuple(
        option
        for cabin_id in range(3)
        for option in (
            DddTrajectoryPassengerOption(
                id=f"conflict_{cabin_id}",
                cabin_id=cabin_id,
                rides=(
                    DddTrajectoryPassengerRide(
                        id=f"ride_{cabin_id}",
                        demand_group_id="g",
                        upper_bound=1.0,
                        objective_delta=-1.0,
                        onboard_segment_ids=("segment",),
                    ),
                ),
            ),
            DddTrajectoryPassengerOption(
                id=f"safe_{cabin_id}",
                cabin_id=cabin_id,
                rides=(),
            ),
        )
    )
    options = tuple(sorted(options, key=lambda option: option.id))
    pairs = tuple(
        (f"conflict_{first}", f"conflict_{second}")
        for first in range(3)
        for second in range(first + 1, 3)
    )
    base = DddTrajectoryPassengerMasterProblem(
        cabin_ids=(0, 1, 2),
        demand_by_group_id={"g": 3.0},
        options=options,
        cabin_capacity=1.0,
        objective_constant=0.0,
        incompatibility_pairs=pairs,
    )
    window = DddTrajectoryResourceWindow("merge", 1)
    clique = DddTrajectoryResourceWindowRow(
        window=window,
        coefficients=tuple((f"conflict_{cabin_id}", 1) for cabin_id in range(3)),
    )

    pair_lp = DddTrajectoryFactorizedLpOptimizer().solve(base)
    clique_lp = DddTrajectoryFactorizedLpOptimizer().solve(
        DddTrajectoryPassengerMasterProblem(
            **{
                **base.__dict__,
                "resource_window_rows": (clique,),
            }
        )
    )

    assert pair_lp.objective_value == pytest.approx(-1.5)
    assert clique_lp.objective_value == pytest.approx(-1.0)
    assert clique_lp.duals is not None
    assert clique_lp.duals.resource_window_raw_by_row_id[window.id] <= 0.0
