from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.examples.three_station import build_three_station_scenario
from ropeway_skip_stop_optimization.examples.three_station_ean import (
    build_three_station_ean_config,
    build_three_station_ean_ring_switch_order,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EarliestAllStopEanMovementPlanBuilder,
    EanRouteDecision,
    network_ean_builder_for_cycle,
)


def test_earliest_all_stop_baseline_builds_plan_from_three_station_artifact() -> None:
    scenario = build_three_station_scenario()
    config = build_three_station_ean_config(scenario)
    artifact = network_ean_builder_for_cycle(
        state_ids=build_three_station_ean_ring_switch_order(scenario),
    ).build(scenario, config)

    plan = EarliestAllStopEanMovementPlanBuilder().build(artifact)

    plan.validate()
    assert plan.scenario_id == artifact.scenario_id
    assert plan.horizon_seconds == artifact.config.horizon_seconds
    assert plan.model_end_seconds == artifact.config.model_end_seconds
    assert {trajectory.cabin_id for trajectory in plan.trajectories} == {0, 1, 2, 3}
    assert all(
        visit.decision is EanRouteDecision.STOP
        for trajectory in plan.trajectories
        for visit in trajectory.visits
    )
    assert all(
        visit.wait_seconds == 0.0
        for trajectory in plan.trajectories
        for visit in trajectory.visits
    )


def test_earliest_all_stop_baseline_propagates_first_visit_times_from_starts_and_timings() -> None:
    scenario = build_three_station_scenario()
    config = build_three_station_ean_config(scenario)
    artifact = network_ean_builder_for_cycle(
        state_ids=build_three_station_ean_ring_switch_order(scenario),
    ).build(scenario, config)

    plan = EarliestAllStopEanMovementPlanBuilder().build(artifact)

    trajectory_by_cabin = {trajectory.cabin_id: trajectory for trajectory in plan.trajectories}
    cabin_0_first_visit = trajectory_by_cabin[0].visits[0]
    cabin_1_first_visit = trajectory_by_cabin[1].visits[0]

    assert cabin_0_first_visit.switch_id == "M_entry_lr"
    assert cabin_0_first_visit.switch_time_seconds == pytest.approx(3 / 2.75 + 150 / 5)
    assert cabin_0_first_visit.platform_entry_time_seconds == pytest.approx(
        cabin_0_first_visit.switch_time_seconds + 5 / 5 + 3 / 2.75
    )
    assert cabin_0_first_visit.platform_exit_time_seconds == pytest.approx(
        cabin_0_first_visit.platform_entry_time_seconds + 10 / 0.5
    )
    assert cabin_0_first_visit.exit_switch_time_seconds == pytest.approx(
        cabin_0_first_visit.platform_exit_time_seconds + 3 / 2.75 + 5 / 5
    )
    assert cabin_0_first_visit.next_switch_time_seconds == pytest.approx(
        cabin_0_first_visit.exit_switch_time_seconds + 150 / 5
    )

    assert cabin_1_first_visit.switch_id == "M_entry_rl"
    assert cabin_1_first_visit.switch_time_seconds == pytest.approx(3 / 2.75 + 150 / 5)


def test_earliest_all_stop_baseline_keeps_trajectory_times_monotonic() -> None:
    scenario = build_three_station_scenario()
    config = build_three_station_ean_config(scenario)
    artifact = network_ean_builder_for_cycle(
        state_ids=build_three_station_ean_ring_switch_order(scenario),
    ).build(scenario, config)

    plan = EarliestAllStopEanMovementPlanBuilder().build(artifact)

    for trajectory in plan.trajectories:
        for previous_visit, next_visit in zip(trajectory.visits, trajectory.visits[1:]):
            assert next_visit.switch_time_seconds == pytest.approx(previous_visit.next_switch_time_seconds)
