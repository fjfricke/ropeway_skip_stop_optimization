from __future__ import annotations

from dataclasses import replace
from datetime import time

import pytest

from ropeway_skip_stop_optimization.baselines import build_maximal_greedy_all_stop_circulation_plan
from ropeway_skip_stop_optimization.examples.three_station import build_three_station_scenario
from ropeway_skip_stop_optimization.models import Demand
from ropeway_skip_stop_optimization.mapping import discretize_scenario
from ropeway_skip_stop_optimization.replay import build_replay_metrics, replay_passenger_boarding


def test_replay_metrics_aggregate_near_capacity_replay() -> None:
    discrete, replay = _discrete_and_replay()

    metrics = build_replay_metrics(discrete, replay)

    assert len(metrics.steps) == discrete.horizon_steps + 1
    assert metrics.steps[0].arrivals_count == 3480
    assert metrics.steps[0].waiting_count == 3480
    assert metrics.steps[0].cumulative_waiting_passenger_hours == pytest.approx(1740.0 / 3600)
    assert [(metric.station_id, metric.count) for metric in metrics.steps[0].waiting_by_station] == [
        ("L", 1160),
        ("M", 1160),
        ("R", 1160),
    ]
    assert metrics.steps[6].boarding_count == 8
    assert metrics.steps[6].onboard_count == 8
    assert [(metric.origin, metric.destination, metric.count) for metric in metrics.steps[6].onboard_by_od] == [
        ("M", "L", 8),
    ]
    assert metrics.steps[-1].waiting_count == replay.summary.unserved_passengers
    assert metrics.steps[-1].onboard_count == replay.summary.onboard_passengers
    assert metrics.steps[-1].cumulative_waiting_passenger_hours == pytest.approx(
        replay.summary.total_waiting_steps * discrete.delta_seconds / 3600
    )


def test_replay_metrics_cumulative_waiting_includes_unserved_backlog() -> None:
    scenario = replace(
        build_three_station_scenario(),
        demands=(Demand(arrival_time=time(8, 20), origin="L", destination="R", count=8),),
    )
    scenario.validate()
    discrete = discretize_scenario(scenario)
    plan = build_maximal_greedy_all_stop_circulation_plan(discrete, discrete.horizon_steps)
    replay = replay_passenger_boarding(discrete, plan)

    metrics = build_replay_metrics(discrete, replay)

    assert replay.summary.total_waiting_steps == 0
    assert replay.summary.unserved_passengers == 8
    assert metrics.steps[-1].waiting_count == 8
    assert metrics.steps[-1].cumulative_waiting_passenger_hours == pytest.approx(8 * discrete.delta_seconds / 3600)


def test_replay_metrics_rejects_mismatched_replay() -> None:
    discrete, replay = _discrete_and_replay()
    bad_replay = replace(replay, discrete_scenario_id="other")

    try:
        build_replay_metrics(discrete, bad_replay)
    except ValueError as error:
        assert "does not belong" in str(error)
    else:
        raise AssertionError("expected mismatched replay to fail")


def _discrete_and_replay():
    discrete = discretize_scenario(build_three_station_scenario())
    plan = build_maximal_greedy_all_stop_circulation_plan(discrete, discrete.horizon_steps)
    replay = replay_passenger_boarding(discrete, plan)
    return discrete, replay
