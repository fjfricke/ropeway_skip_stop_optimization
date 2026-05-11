from __future__ import annotations

from dataclasses import dataclass, replace

from ropeway_skip_stop_optimization.models import (
    AlightingEvent,
    BoardingEvent,
    BoardingPolicyKind,
    CabinLoadState,
    CabinTrajectory,
    DiscreteNode,
    DiscreteScenario,
    MovementPlan,
    OnboardPassengerGroup,
    PassengerQueueState,
    QueueItem,
    ReplayResult,
    ReplayStepState,
    ReplaySummary,
    validate_movement_plan,
)


@dataclass(frozen=True)
class ReplayConfig:
    boarding_policy: BoardingPolicyKind = BoardingPolicyKind.GREEDY_FIFO_NEXT_COMPATIBLE_CABIN
    allow_same_step_demand_boarding: bool = True
    alight_before_board: bool = True

    def validate(self) -> None:
        if self.boarding_policy is not BoardingPolicyKind.GREEDY_FIFO_NEXT_COMPATIBLE_CABIN:
            raise NotImplementedError(f"unsupported boarding policy: {self.boarding_policy}")


def replay_passenger_boarding(
    discrete_scenario: DiscreteScenario,
    movement_plan: MovementPlan,
    config: ReplayConfig | None = None,
) -> ReplayResult:
    config = config or ReplayConfig()
    config.validate()
    validate_movement_plan(movement_plan, discrete_scenario)

    node_by_id = {node.id: node for node in discrete_scenario.nodes}
    waiting_pools: dict[str, list[QueueItem]] = {}
    onboard_by_cabin: dict[int, list[OnboardPassengerGroup]] = {
        trajectory.cabin_id: []
        for trajectory in movement_plan.trajectories
    }

    all_boarding_events: list[BoardingEvent] = []
    all_alighting_events: list[AlightingEvent] = []
    step_states: list[ReplayStepState] = []

    for time_step in range(movement_plan.horizon_steps + 1):
        if config.allow_same_step_demand_boarding:
            _add_demand_arrivals(discrete_scenario, time_step, waiting_pools)

        step_alighting_events: list[AlightingEvent] = []
        step_boarding_events: list[BoardingEvent] = []

        if config.alight_before_board:
            step_alighting_events.extend(
                _process_alighting(discrete_scenario, movement_plan, time_step, node_by_id, onboard_by_cabin)
            )
            step_boarding_events.extend(
                _process_boarding(discrete_scenario, movement_plan, time_step, node_by_id, waiting_pools, onboard_by_cabin)
            )
        else:
            step_boarding_events.extend(
                _process_boarding(discrete_scenario, movement_plan, time_step, node_by_id, waiting_pools, onboard_by_cabin)
            )
            step_alighting_events.extend(
                _process_alighting(discrete_scenario, movement_plan, time_step, node_by_id, onboard_by_cabin)
            )

        if not config.allow_same_step_demand_boarding:
            _add_demand_arrivals(discrete_scenario, time_step, waiting_pools)

        all_boarding_events.extend(step_boarding_events)
        all_alighting_events.extend(step_alighting_events)
        step_state = ReplayStepState(
            time_step=time_step,
            queue_states=_queue_states(time_step, waiting_pools),
            cabin_loads=_cabin_load_states(time_step, movement_plan, node_by_id, onboard_by_cabin),
            boarding_events=tuple(step_boarding_events),
            alighting_events=tuple(step_alighting_events),
        )
        step_state.validate(discrete_scenario.cabin_capacity)
        step_states.append(step_state)

    final_queue_states = step_states[-1].queue_states if step_states else ()
    final_cabin_loads = step_states[-1].cabin_loads if step_states else ()
    summary = _summary(discrete_scenario, all_boarding_events, all_alighting_events, final_queue_states, final_cabin_loads)
    result = ReplayResult(
        discrete_scenario_id=discrete_scenario.id,
        movement_plan_horizon_steps=movement_plan.horizon_steps,
        boarding_policy=config.boarding_policy,
        steps=tuple(step_states),
        boarding_events=tuple(all_boarding_events),
        alighting_events=tuple(all_alighting_events),
        final_queue_states=final_queue_states,
        final_cabin_loads=final_cabin_loads,
        summary=summary,
    )
    result.validate(discrete_scenario.cabin_capacity)
    return result


def can_cabin_serve_destination_from_step(
    discrete_scenario: DiscreteScenario,
    trajectory: CabinTrajectory,
    time_step: int,
    origin_station_id: str,
    destination_station_id: str,
) -> bool:
    if origin_station_id == destination_station_id:
        return False
    if not 0 <= time_step < len(trajectory.positions):
        raise ValueError("time_step is outside trajectory positions")

    node_by_id = {node.id: node for node in discrete_scenario.nodes}
    return _can_cabin_serve_destination_from_step(
        trajectory,
        time_step,
        origin_station_id,
        destination_station_id,
        node_by_id,
    )


def _add_demand_arrivals(
    discrete_scenario: DiscreteScenario,
    time_step: int,
    waiting_pools: dict[str, list[QueueItem]],
) -> None:
    for demand_index, demand in enumerate(discrete_scenario.demands):
        if demand.time_step != time_step:
            continue
        item = QueueItem(
            batch_id=f"demand::{demand_index}",
            demand_index=demand_index,
            origin=demand.origin,
            destination=demand.destination,
            arrival_step=demand.time_step,
            remaining_count=demand.count,
        )
        item.validate()
        waiting_pools.setdefault(demand.origin, []).append(item)


def _process_alighting(
    discrete_scenario: DiscreteScenario,
    movement_plan: MovementPlan,
    time_step: int,
    node_by_id: dict[str, DiscreteNode],
    onboard_by_cabin: dict[int, list[OnboardPassengerGroup]],
) -> tuple[AlightingEvent, ...]:
    events: list[AlightingEvent] = []
    for trajectory in movement_plan.trajectories:
        position = trajectory.positions[time_step]
        node = node_by_id[position.node_id]
        if not node.allows_alighting or node.station_id is None:
            continue

        remaining_groups: list[OnboardPassengerGroup] = []
        for group in onboard_by_cabin[trajectory.cabin_id]:
            if group.destination != node.station_id:
                remaining_groups.append(group)
                continue
            event = AlightingEvent(
                time_step=time_step,
                cabin_id=trajectory.cabin_id,
                station_id=node.station_id,
                batch_id=group.batch_id,
                count=group.count,
                onboard_steps=time_step - group.boarded_step,
            )
            event.validate()
            events.append(event)
        onboard_by_cabin[trajectory.cabin_id] = remaining_groups

    return tuple(events)


def _process_boarding(
    discrete_scenario: DiscreteScenario,
    movement_plan: MovementPlan,
    time_step: int,
    node_by_id: dict[str, DiscreteNode],
    waiting_pools: dict[str, list[QueueItem]],
    onboard_by_cabin: dict[int, list[OnboardPassengerGroup]],
) -> tuple[BoardingEvent, ...]:
    events: list[BoardingEvent] = []
    trajectories = tuple(sorted(movement_plan.trajectories, key=lambda trajectory: trajectory.cabin_id))
    for trajectory in trajectories:
        position = trajectory.positions[time_step]
        node = node_by_id[position.node_id]
        if not node.allows_boarding or node.station_id is None:
            continue

        free_capacity = discrete_scenario.cabin_capacity - _load_count(onboard_by_cabin[trajectory.cabin_id])
        if free_capacity <= 0:
            continue

        station_pool = waiting_pools.get(node.station_id, [])
        if not station_pool:
            continue

        updated_pool: list[QueueItem] = []
        for item in sorted(station_pool, key=lambda queue_item: (queue_item.arrival_step, queue_item.demand_index)):
            if free_capacity <= 0:
                updated_pool.append(item)
                continue
            if not _can_cabin_serve_destination_from_step(
                trajectory,
                time_step,
                item.origin,
                item.destination,
                node_by_id,
            ):
                updated_pool.append(item)
                continue

            boarded_count = min(free_capacity, item.remaining_count)
            onboard_group = OnboardPassengerGroup(
                batch_id=item.batch_id,
                demand_index=item.demand_index,
                origin=item.origin,
                destination=item.destination,
                arrival_step=item.arrival_step,
                boarded_step=time_step,
                count=boarded_count,
            )
            onboard_group.validate()
            onboard_by_cabin[trajectory.cabin_id].append(onboard_group)

            event = BoardingEvent(
                time_step=time_step,
                cabin_id=trajectory.cabin_id,
                station_id=node.station_id,
                destination=item.destination,
                batch_id=item.batch_id,
                count=boarded_count,
                waiting_steps=time_step - item.arrival_step,
            )
            event.validate()
            events.append(event)

            free_capacity -= boarded_count
            remaining_count = item.remaining_count - boarded_count
            if remaining_count > 0:
                updated_pool.append(replace(item, remaining_count=remaining_count))

        if updated_pool:
            waiting_pools[node.station_id] = updated_pool
        else:
            waiting_pools.pop(node.station_id, None)

    return tuple(events)


def _can_cabin_serve_destination_from_step(
    trajectory: CabinTrajectory,
    time_step: int,
    origin_station_id: str,
    destination_station_id: str,
    node_by_id: dict[str, DiscreteNode],
) -> bool:
    seen_other_alighting_station = False
    for position in trajectory.positions[time_step + 1 :]:
        node = node_by_id[position.node_id]
        if not node.allows_alighting or node.station_id is None:
            continue
        if node.station_id == destination_station_id:
            return True
        if node.station_id != origin_station_id:
            seen_other_alighting_station = True
            continue
        if seen_other_alighting_station:
            return False
    return False


def _queue_states(
    time_step: int,
    waiting_pools: dict[str, list[QueueItem]],
) -> tuple[PassengerQueueState, ...]:
    waiting_by_od: dict[tuple[str, str], int] = {}
    for station_id, pool in waiting_pools.items():
        for item in pool:
            key = (station_id, item.destination)
            waiting_by_od[key] = waiting_by_od.get(key, 0) + item.remaining_count

    states = tuple(
        PassengerQueueState(
            time_step=time_step,
            station_id=station_id,
            destination=destination,
            waiting_count=waiting_count,
        )
        for (station_id, destination), waiting_count in sorted(waiting_by_od.items())
    )
    for state in states:
        state.validate()
    return states


def _cabin_load_states(
    time_step: int,
    movement_plan: MovementPlan,
    node_by_id: dict[str, DiscreteNode],
    onboard_by_cabin: dict[int, list[OnboardPassengerGroup]],
) -> tuple[CabinLoadState, ...]:
    states = tuple(
        CabinLoadState(
            time_step=time_step,
            cabin_id=trajectory.cabin_id,
            node_id=trajectory.positions[time_step].node_id,
            onboard_groups=tuple(onboard_by_cabin[trajectory.cabin_id]),
        )
        for trajectory in sorted(movement_plan.trajectories, key=lambda item: item.cabin_id)
    )
    # Touch node_by_id here to fail loudly if a trajectory state is inconsistent with the scenario.
    for state in states:
        if state.node_id not in node_by_id:
            raise ValueError(f"cabin load references unknown node_id {state.node_id!r}")
    return states


def _summary(
    discrete_scenario: DiscreteScenario,
    boarding_events: list[BoardingEvent],
    alighting_events: list[AlightingEvent],
    final_queue_states: tuple[PassengerQueueState, ...],
    final_cabin_loads: tuple[CabinLoadState, ...],
) -> ReplaySummary:
    arrived_passengers = sum(demand.count for demand in discrete_scenario.demands)
    boarded_passengers = sum(event.count for event in boarding_events)
    served_passengers = sum(event.count for event in alighting_events)
    unserved_passengers = sum(state.waiting_count for state in final_queue_states)
    onboard_passengers = sum(state.load_count for state in final_cabin_loads)
    total_waiting_steps = sum(event.count * event.waiting_steps for event in boarding_events)
    max_waiting_steps = max((event.waiting_steps for event in boarding_events), default=0)
    summary = ReplaySummary(
        arrived_passengers=arrived_passengers,
        boarded_passengers=boarded_passengers,
        served_passengers=served_passengers,
        unserved_passengers=unserved_passengers,
        onboard_passengers=onboard_passengers,
        total_waiting_steps=total_waiting_steps,
        max_waiting_steps=max_waiting_steps,
    )
    summary.validate()
    return summary


def _load_count(groups: list[OnboardPassengerGroup]) -> int:
    return sum(group.count for group in groups)
