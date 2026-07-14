from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.optimization.ean import (
    EanCabinTrajectory,
    EanCabinVisit,
    EanHorizonFormulation,
    EanMovementPlan,
    EanRouteDecision,
)


def test_ean_stop_visit_validates_platform_times() -> None:
    visit = _stop_visit()

    visit.validate()

    with pytest.raises(ValueError, match="platform entry and exit"):
        _stop_visit(platform_entry_time_seconds=None).validate()

    with pytest.raises(ValueError, match="monotonic"):
        _stop_visit(platform_exit_time_seconds=20.0, exit_switch_time_seconds=19.0).validate()


def test_ean_skip_visit_validates_without_platform_times_or_waiting() -> None:
    visit = _skip_visit()

    visit.validate()

    with pytest.raises(ValueError, match="must not set platform"):
        _skip_visit(platform_entry_time_seconds=11.0).validate()

    with pytest.raises(ValueError, match="must not wait"):
        _skip_visit(wait_seconds=1.0).validate()


def test_ean_trajectory_requires_ordered_contiguous_visits_for_one_cabin() -> None:
    trajectory = EanCabinTrajectory(
        cabin_id=0,
        visits=(
            _stop_visit(cabin_id=0, visit_index=0, next_switch_time_seconds=40.0),
            _stop_visit(
                cabin_id=0,
                visit_index=1,
                switch_time_seconds=40.0,
                platform_entry_time_seconds=42.0,
                platform_exit_time_seconds=52.0,
                exit_switch_time_seconds=54.0,
                next_switch_time_seconds=84.0,
            ),
        ),
    )

    trajectory.validate()

    with pytest.raises(ValueError, match="contiguous"):
        EanCabinTrajectory(cabin_id=0, visits=(_stop_visit(visit_index=1),)).validate()

    with pytest.raises(ValueError, match="another cabin"):
        EanCabinTrajectory(cabin_id=0, visits=(_stop_visit(cabin_id=1),)).validate()


def test_ean_movement_plan_validates_duplicate_cabins_and_horizon() -> None:
    plan = EanMovementPlan(
        scenario_id="scenario",
        horizon_seconds=120.0,
        model_end_seconds=180.0,
        trajectories=(
            EanCabinTrajectory(cabin_id=0, visits=(_stop_visit(cabin_id=0),)),
            EanCabinTrajectory(cabin_id=1, visits=(_skip_visit(cabin_id=1),)),
        ),
    )

    plan.validate()

    with pytest.raises(ValueError, match="at least horizon"):
        EanMovementPlan(
            scenario_id="scenario",
            horizon_seconds=120.0,
            model_end_seconds=119.0,
            trajectories=(EanCabinTrajectory(cabin_id=0, visits=(_stop_visit(cabin_id=0),)),),
        ).validate()


def test_empty_ean_trajectory_requires_exact_horizon_activation() -> None:
    trajectory = EanCabinTrajectory(cabin_id=0, visits=())

    EanMovementPlan(
        scenario_id="scenario",
        horizon_seconds=10.0,
        model_end_seconds=10.0,
        trajectories=(trajectory,),
        horizon_formulation=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
    ).validate()

    with pytest.raises(ValueError, match="exact horizon activation"):
        EanMovementPlan(
            scenario_id="scenario",
            horizon_seconds=10.0,
            model_end_seconds=10.0,
            trajectories=(trajectory,),
        ).validate()

    with pytest.raises(ValueError, match="duplicate cabin"):
        EanMovementPlan(
            scenario_id="scenario",
            horizon_seconds=120.0,
            model_end_seconds=180.0,
            trajectories=(
                EanCabinTrajectory(cabin_id=0, visits=(_stop_visit(cabin_id=0),)),
                EanCabinTrajectory(cabin_id=0, visits=(_skip_visit(cabin_id=0),)),
            ),
        ).validate()


def _stop_visit(
    cabin_id: int = 0,
    visit_index: int = 0,
    switch_time_seconds: float = 10.0,
    platform_entry_time_seconds: float | None = 12.0,
    platform_exit_time_seconds: float | None = 22.0,
    exit_switch_time_seconds: float = 24.0,
    next_switch_time_seconds: float = 54.0,
    wait_seconds: float = 0.0,
) -> EanCabinVisit:
    return EanCabinVisit(
        cabin_id=cabin_id,
        visit_index=visit_index,
        switch_id="M_entry_lr",
        station_id="M",
        decision=EanRouteDecision.STOP,
        switch_time_seconds=switch_time_seconds,
        platform_entry_time_seconds=platform_entry_time_seconds,
        platform_exit_time_seconds=platform_exit_time_seconds,
        exit_switch_time_seconds=exit_switch_time_seconds,
        next_switch_time_seconds=next_switch_time_seconds,
        wait_seconds=wait_seconds,
    )


def _skip_visit(
    cabin_id: int = 0,
    visit_index: int = 0,
    switch_time_seconds: float = 10.0,
    platform_entry_time_seconds: float | None = None,
    platform_exit_time_seconds: float | None = None,
    exit_switch_time_seconds: float = 20.0,
    next_switch_time_seconds: float = 50.0,
    wait_seconds: float = 0.0,
) -> EanCabinVisit:
    return EanCabinVisit(
        cabin_id=cabin_id,
        visit_index=visit_index,
        switch_id="M_entry_lr",
        station_id="M",
        decision=EanRouteDecision.SKIP,
        switch_time_seconds=switch_time_seconds,
        platform_entry_time_seconds=platform_entry_time_seconds,
        platform_exit_time_seconds=platform_exit_time_seconds,
        exit_switch_time_seconds=exit_switch_time_seconds,
        next_switch_time_seconds=next_switch_time_seconds,
        wait_seconds=wait_seconds,
    )
