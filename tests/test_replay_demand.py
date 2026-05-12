from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.examples.three_station import build_three_station_scenario
from ropeway_skip_stop_optimization.mapping import discretize_scenario
from ropeway_skip_stop_optimization.replay import (
    cumulative_passenger_queues,
    demand_arrivals_at_step,
    total_waiting_count,
)


def test_demand_arrivals_at_step_returns_fixed_batches() -> None:
    discrete = discretize_scenario(build_three_station_scenario())

    arrivals = demand_arrivals_at_step(discrete, 0)

    assert len(arrivals) == 6
    assert arrivals[0].demand_index == 0
    assert arrivals[0].origin == "L"
    assert arrivals[0].destination == "M"
    assert arrivals[0].count == 580
    assert demand_arrivals_at_step(discrete, 120) == ()


def test_cumulative_passenger_queues_accumulate_without_boarding() -> None:
    discrete = discretize_scenario(build_three_station_scenario())

    assert _queue_map(cumulative_passenger_queues(discrete, 0)) == {
        ("L", "M"): 580,
        ("L", "R"): 580,
        ("M", "L"): 580,
        ("M", "R"): 580,
        ("R", "L"): 580,
        ("R", "M"): 580,
    }
    final_queues = cumulative_passenger_queues(discrete, 1080)
    assert _queue_map(final_queues) == {
        ("L", "M"): 580,
        ("L", "R"): 580,
        ("M", "L"): 580,
        ("M", "R"): 580,
        ("R", "L"): 580,
        ("R", "M"): 580,
    }
    assert total_waiting_count(final_queues) == 3480


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
