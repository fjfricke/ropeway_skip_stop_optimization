from __future__ import annotations

from ropeway_skip_stop_optimization.models import (
    DemandArrivalEvent,
    DiscreteScenario,
    PassengerQueueState,
)


def demand_arrivals_at_step(
    discrete_scenario: DiscreteScenario,
    time_step: int,
) -> tuple[DemandArrivalEvent, ...]:
    _validate_time_step(discrete_scenario, time_step)

    events = tuple(
        DemandArrivalEvent(
            demand_index=index,
            time_step=demand.time_step,
            origin=demand.origin,
            destination=demand.destination,
            count=demand.count,
        )
        for index, demand in enumerate(discrete_scenario.demands)
        if demand.time_step == time_step
    )
    for event in events:
        event.validate()
    return events


def cumulative_passenger_queues(
    discrete_scenario: DiscreteScenario,
    time_step: int,
) -> tuple[PassengerQueueState, ...]:
    _validate_time_step(discrete_scenario, time_step)

    waiting_by_od: dict[tuple[str, str], int] = {}
    for demand in discrete_scenario.demands:
        if demand.time_step > time_step:
            continue
        key = (demand.origin, demand.destination)
        waiting_by_od[key] = waiting_by_od.get(key, 0) + demand.count

    states = tuple(
        PassengerQueueState(
            time_step=time_step,
            station_id=origin,
            destination=destination,
            waiting_count=count,
        )
        for (origin, destination), count in sorted(waiting_by_od.items())
    )
    for state in states:
        state.validate()
    return states


def total_waiting_count(queue_states: tuple[PassengerQueueState, ...]) -> int:
    return sum(state.waiting_count for state in queue_states)


def _validate_time_step(discrete_scenario: DiscreteScenario, time_step: int) -> None:
    if not 0 <= time_step <= discrete_scenario.horizon_steps:
        raise ValueError("time_step is outside the discrete scenario horizon")
