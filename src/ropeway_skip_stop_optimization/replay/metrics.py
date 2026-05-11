from __future__ import annotations

from ropeway_skip_stop_optimization.models import (
    CabinLoadState,
    DiscreteScenario,
    PassengerOdMetric,
    PassengerQueueState,
    PassengerStationMetric,
    ReplayMetrics,
    ReplayMetricsStep,
    ReplayResult,
)


def build_replay_metrics(
    discrete_scenario: DiscreteScenario,
    replay_result: ReplayResult,
) -> ReplayMetrics:
    if replay_result.discrete_scenario_id != discrete_scenario.id:
        raise ValueError("replay result does not belong to the discrete scenario")
    if replay_result.movement_plan_horizon_steps != discrete_scenario.horizon_steps:
        raise ValueError("replay result horizon does not match the discrete scenario")

    arrivals_by_step: dict[int, int] = {}
    for demand in discrete_scenario.demands:
        arrivals_by_step[demand.time_step] = arrivals_by_step.get(demand.time_step, 0) + demand.count

    cumulative_waiting_passenger_hours = 0.0
    metric_steps: list[ReplayMetricsStep] = []
    for step in replay_result.steps:
        waiting_by_station = _waiting_by_station(step.queue_states)
        onboard_by_od = _onboard_by_od(step.cabin_loads)
        waiting_count = sum(metric.count for metric in waiting_by_station)
        onboard_count = sum(metric.count for metric in onboard_by_od)
        cumulative_waiting_passenger_hours += waiting_count * discrete_scenario.delta_seconds / 3600

        metric_step = ReplayMetricsStep(
            time_step=step.time_step,
            arrivals_count=arrivals_by_step.get(step.time_step, 0),
            boarding_count=sum(event.count for event in step.boarding_events),
            alighting_count=sum(event.count for event in step.alighting_events),
            waiting_count=waiting_count,
            onboard_count=onboard_count,
            cumulative_waiting_passenger_hours=cumulative_waiting_passenger_hours,
            waiting_by_station=waiting_by_station,
            onboard_by_od=onboard_by_od,
        )
        metric_step.validate()
        metric_steps.append(metric_step)

    metrics = ReplayMetrics(
        discrete_scenario_id=discrete_scenario.id,
        movement_plan_horizon_steps=replay_result.movement_plan_horizon_steps,
        delta_seconds=discrete_scenario.delta_seconds,
        steps=tuple(metric_steps),
    )
    metrics.validate()
    return metrics


def _waiting_by_station(queue_states: tuple[PassengerQueueState, ...]) -> tuple[PassengerStationMetric, ...]:
    waiting_by_station: dict[str, int] = {}
    for state in queue_states:
        waiting_by_station[state.station_id] = waiting_by_station.get(state.station_id, 0) + state.waiting_count
    return tuple(
        PassengerStationMetric(station_id=station_id, count=count)
        for station_id, count in sorted(waiting_by_station.items())
        if count > 0
    )


def _onboard_by_od(cabin_loads: tuple[CabinLoadState, ...]) -> tuple[PassengerOdMetric, ...]:
    onboard_by_od: dict[tuple[str, str], int] = {}
    for load in cabin_loads:
        for group in load.onboard_groups:
            key = (group.origin, group.destination)
            onboard_by_od[key] = onboard_by_od.get(key, 0) + group.count
    return tuple(
        PassengerOdMetric(origin=origin, destination=destination, count=count)
        for (origin, destination), count in sorted(onboard_by_od.items())
        if count > 0
    )
