from __future__ import annotations

from dataclasses import replace
from datetime import time

from ropeway_skip_stop_optimization.baselines import build_maximal_greedy_all_stop_circulation_plan
from ropeway_skip_stop_optimization.examples import build_three_station_scenario
from ropeway_skip_stop_optimization.models import Demand
from ropeway_skip_stop_optimization.preprocessing.discretize import discretize_scenario
from ropeway_skip_stop_optimization.replay import (
    can_cabin_serve_destination_from_step,
    replay_passenger_boarding,
)


def test_reachability_defines_current_direction_from_trajectory() -> None:
    discrete, plan = _discrete_and_plan()
    node_by_id = {node.id: node for node in discrete.nodes}
    trajectory = plan.trajectories[0]
    m_boarding_position = next(
        position
        for position in trajectory.positions
        if node_by_id[position.node_id].allows_boarding
        and node_by_id[position.node_id].station_id == "M"
    )

    assert can_cabin_serve_destination_from_step(
        discrete,
        trajectory,
        m_boarding_position.time_step,
        origin_station_id="M",
        destination_station_id="R",
    )
    assert not can_cabin_serve_destination_from_step(
        discrete,
        trajectory,
        m_boarding_position.time_step,
        origin_station_id="M",
        destination_station_id="L",
    )


def test_greedy_passenger_replay_boards_and_alights_fixed_demands() -> None:
    discrete, plan = _discrete_and_plan()

    result = replay_passenger_boarding(discrete, plan)

    assert result.summary.arrived_passengers == 52
    assert result.summary.boarded_passengers == 52
    assert result.summary.served_passengers == 52
    assert result.summary.unserved_passengers == 0
    assert result.summary.onboard_passengers == 0
    assert result.summary.total_waiting_steps == 56
    assert result.summary.max_waiting_steps == 14
    assert result.steps[120].boarding_events[0].station_id == "L"
    assert result.steps[120].boarding_events[0].destination == "R"
    assert result.steps[120].boarding_events[0].count == 8
    assert result.steps[120].queue_states[0].waiting_count == 4
    assert result.steps[134].boarding_events[0].count == 4
    assert result.steps[134].boarding_events[0].waiting_steps == 14
    assert any(event.batch_id == "demand::0" and event.station_id == "R" for event in result.alighting_events)


def test_greedy_passenger_replay_splits_batch_across_next_compatible_cabins_when_full() -> None:
    scenario = build_three_station_scenario()
    scenario = replace(
        scenario,
        demands=(Demand(arrival_time=time(8, 1), origin="L", destination="R", count=11),),
    )
    scenario.validate()
    discrete = discretize_scenario(scenario)
    plan = build_maximal_greedy_all_stop_circulation_plan(discrete, horizon_steps=discrete.horizon_steps)

    result = replay_passenger_boarding(discrete, plan)

    assert result.steps[120].boarding_events == result.boarding_events[:2]
    assert [event.count for event in result.steps[120].boarding_events] == [8, 3]
    assert [event.cabin_id for event in result.steps[120].boarding_events] == [14, 15]
    assert result.steps[120].queue_states == ()
    assert result.summary.arrived_passengers == 11
    assert result.summary.served_passengers == 11


def test_greedy_passenger_replay_accounting_balances_with_unserved_backlog() -> None:
    scenario = build_three_station_scenario()
    scenario = replace(
        scenario,
        demands=(Demand(arrival_time=time(8, 19), origin="L", destination="R", count=8),),
    )
    scenario.validate()
    discrete = discretize_scenario(scenario)
    plan = build_maximal_greedy_all_stop_circulation_plan(discrete, horizon_steps=discrete.horizon_steps)

    result = replay_passenger_boarding(discrete, plan)

    assert result.summary.arrived_passengers == (
        result.summary.served_passengers
        + result.summary.unserved_passengers
        + result.summary.onboard_passengers
    )


def _discrete_and_plan():
    discrete = discretize_scenario(build_three_station_scenario())
    plan = build_maximal_greedy_all_stop_circulation_plan(discrete, horizon_steps=discrete.horizon_steps)
    return discrete, plan
