from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.examples import build_three_station_scenario
from ropeway_skip_stop_optimization.preprocessing.discretize import discretize_scenario
from ropeway_skip_stop_optimization.replay import (
    cumulative_passenger_queues,
    demand_arrivals_at_step,
    total_waiting_count,
)


def test_demand_arrivals_at_step_returns_fixed_batches() -> None:
    discrete = discretize_scenario(build_three_station_scenario())

    assert demand_arrivals_at_step(discrete, 0) == ()
    arrivals = demand_arrivals_at_step(discrete, 120)

    assert len(arrivals) == 1
    assert arrivals[0].demand_index == 0
    assert arrivals[0].origin == "L"
    assert arrivals[0].destination == "R"
    assert arrivals[0].count == 20


def test_cumulative_passenger_queues_accumulate_without_boarding() -> None:
    discrete = discretize_scenario(build_three_station_scenario())

    assert cumulative_passenger_queues(discrete, 0) == ()
    assert _queue_map(cumulative_passenger_queues(discrete, 120)) == {("L", "R"): 20}
    assert _queue_map(cumulative_passenger_queues(discrete, 240)) == {
        ("L", "R"): 20,
        ("L", "M"): 4,
    }
    final_queues = cumulative_passenger_queues(discrete, 1080)
    assert _queue_map(final_queues) == {
        ("L", "M"): 4,
        ("L", "R"): 25,
        ("M", "L"): 4,
        ("M", "R"): 5,
        ("R", "L"): 11,
        ("R", "M"): 3,
    }
    assert total_waiting_count(final_queues) == 52


def test_cumulative_passenger_queues_rejects_steps_outside_horizon() -> None:
    discrete = discretize_scenario(build_three_station_scenario())

    with pytest.raises(ValueError, match="outside the discrete scenario horizon"):
        cumulative_passenger_queues(discrete, -1)
    with pytest.raises(ValueError, match="outside the discrete scenario horizon"):
        demand_arrivals_at_step(discrete, discrete.horizon_steps + 1)


def _queue_map(queue_states):
    return {
        (state.station_id, state.destination): state.waiting_count
        for state in queue_states
    }
