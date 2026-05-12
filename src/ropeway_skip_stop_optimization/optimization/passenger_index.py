from __future__ import annotations

from dataclasses import dataclass

from ropeway_skip_stop_optimization.models import DiscreteScenario
from ropeway_skip_stop_optimization.optimization.graph_index import DiscreteGraphIndex
from ropeway_skip_stop_optimization.optimization.models import FixedCabinStart, MilpV0VariableIndex


OdPair = tuple[str, str]


@dataclass(frozen=True)
class PassengerMilpIndex:
    od_pairs: tuple[OdPair, ...]
    demand_count_by_time_od: dict[tuple[int, str, str], int]
    total_demand_by_od: dict[OdPair, int]
    boarding_node_ids_by_station: dict[str, tuple[str, ...]]
    alighting_node_ids_by_station: dict[str, tuple[str, ...]]
    boarding_candidates_by_cabin_time_od: dict[tuple[int, int, str, str], tuple[str, ...]]
    alighting_candidates_by_cabin_time_destination: dict[tuple[int, int, str], tuple[str, ...]]
    can_reach_destination_by_cabin_time_destination: dict[tuple[int, int, str], bool]


def build_passenger_milp_index(
    discrete_scenario: DiscreteScenario,
    graph_index: DiscreteGraphIndex,
    variable_index: MilpV0VariableIndex,
    fixed_starts: tuple[FixedCabinStart, ...],
    allowed_arc_ids: tuple[str, ...],
    horizon_steps: int,
) -> PassengerMilpIndex:
    if horizon_steps < 0:
        raise ValueError("passenger MILP index horizon_steps must be nonnegative")
    if horizon_steps > discrete_scenario.horizon_steps:
        raise ValueError("passenger MILP index horizon_steps exceeds discrete scenario horizon")

    cabin_ids = tuple(start.cabin_id for start in fixed_starts)
    od_pairs = _od_pairs(discrete_scenario, horizon_steps)
    destinations = tuple(sorted({destination for _, destination in od_pairs}))
    demand_count_by_time_od = _demand_count_by_time_od(discrete_scenario, horizon_steps)
    total_demand_by_od = {
        od_pair: sum(
            count
            for (time_step, origin, destination), count in demand_count_by_time_od.items()
            if (origin, destination) == od_pair and 0 <= time_step <= horizon_steps
        )
        for od_pair in od_pairs
    }
    boarding_node_ids_by_station = _service_node_ids_by_station(discrete_scenario, allows_boarding=True)
    alighting_node_ids_by_station = _service_node_ids_by_station(discrete_scenario, allows_alighting=True)
    destination_reachable_node_ids_by_time = {
        destination: _destination_reachable_node_ids_by_time(
            graph_index,
            allowed_arc_ids,
            alighting_node_ids_by_station.get(destination, ()),
            horizon_steps,
        )
        for destination in destinations
    }

    boarding_candidates_by_cabin_time_od: dict[tuple[int, int, str, str], tuple[str, ...]] = {}
    alighting_candidates_by_cabin_time_destination: dict[tuple[int, int, str], tuple[str, ...]] = {}
    can_reach_destination_by_cabin_time_destination: dict[tuple[int, int, str], bool] = {}

    for cabin_id in cabin_ids:
        for time_step in range(horizon_steps + 1):
            reachable_node_ids = variable_index.node_ids_by_cabin_time[cabin_id, time_step]
            reachable_node_id_set = set(reachable_node_ids)

            for destination in destinations:
                destination_reachable_node_ids = destination_reachable_node_ids_by_time[destination][time_step]
                can_reach_destination = any(
                    node_id in destination_reachable_node_ids
                    for node_id in reachable_node_ids
                )
                can_reach_destination_by_cabin_time_destination[cabin_id, time_step, destination] = (
                    can_reach_destination
                )

                alighting_candidates = tuple(
                    node_id
                    for node_id in alighting_node_ids_by_station.get(destination, ())
                    if node_id in reachable_node_id_set
                )
                if alighting_candidates:
                    alighting_candidates_by_cabin_time_destination[cabin_id, time_step, destination] = (
                        alighting_candidates
                    )

            for origin, destination in od_pairs:
                destination_reachable_node_ids = destination_reachable_node_ids_by_time[destination][time_step]
                boarding_candidates = tuple(
                    node_id
                    for node_id in boarding_node_ids_by_station.get(origin, ())
                    if node_id in reachable_node_id_set and node_id in destination_reachable_node_ids
                )
                if boarding_candidates:
                    boarding_candidates_by_cabin_time_od[cabin_id, time_step, origin, destination] = (
                        boarding_candidates
                    )

    return PassengerMilpIndex(
        od_pairs=od_pairs,
        demand_count_by_time_od=demand_count_by_time_od,
        total_demand_by_od=total_demand_by_od,
        boarding_node_ids_by_station=boarding_node_ids_by_station,
        alighting_node_ids_by_station=alighting_node_ids_by_station,
        boarding_candidates_by_cabin_time_od=boarding_candidates_by_cabin_time_od,
        alighting_candidates_by_cabin_time_destination=alighting_candidates_by_cabin_time_destination,
        can_reach_destination_by_cabin_time_destination=can_reach_destination_by_cabin_time_destination,
    )


def _od_pairs(discrete_scenario: DiscreteScenario, horizon_steps: int) -> tuple[OdPair, ...]:
    return tuple(
        sorted({
            (demand.origin, demand.destination)
            for demand in _demands_within_horizon(discrete_scenario, horizon_steps)
        })
    )


def _demand_count_by_time_od(
    discrete_scenario: DiscreteScenario,
    horizon_steps: int,
) -> dict[tuple[int, str, str], int]:
    demand_count_by_time_od: dict[tuple[int, str, str], int] = {}
    for demand in _demands_within_horizon(discrete_scenario, horizon_steps):
        key = (demand.time_step, demand.origin, demand.destination)
        demand_count_by_time_od[key] = demand_count_by_time_od.get(key, 0) + demand.count
    return demand_count_by_time_od


def _demands_within_horizon(discrete_scenario: DiscreteScenario, horizon_steps: int):
    return (
        demand
        for demand in discrete_scenario.demands
        if 0 <= demand.time_step <= horizon_steps
    )


def _service_node_ids_by_station(
    discrete_scenario: DiscreteScenario,
    *,
    allows_boarding: bool = False,
    allows_alighting: bool = False,
) -> dict[str, tuple[str, ...]]:
    node_ids_by_station: dict[str, list[str]] = {}
    for node in discrete_scenario.nodes:
        if node.station_id is None:
            continue
        if allows_boarding and not node.allows_boarding:
            continue
        if allows_alighting and not node.allows_alighting:
            continue
        node_ids_by_station.setdefault(node.station_id, []).append(node.id)
    return {
        station_id: tuple(node_ids)
        for station_id, node_ids in sorted(node_ids_by_station.items())
    }


def _destination_reachable_node_ids_by_time(
    graph_index: DiscreteGraphIndex,
    allowed_arc_ids: tuple[str, ...],
    alighting_node_ids: tuple[str, ...],
    horizon_steps: int,
) -> dict[int, frozenset[str]]:
    predecessors_by_node_id: dict[str, list[str]] = {node_id: [] for node_id in graph_index.nodes_by_id}
    for arc_id in allowed_arc_ids:
        arc = graph_index.arcs_by_id[arc_id]
        predecessors_by_node_id[arc.to_node_id].append(arc.from_node_id)

    reachable_by_time: dict[int, frozenset[str]] = {}
    current = set(alighting_node_ids)
    reachable_by_time[horizon_steps] = frozenset(current)
    for time_step in range(horizon_steps - 1, -1, -1):
        previous = set(current)
        for node_id in current:
            previous.update(predecessors_by_node_id[node_id])
        current = previous
        reachable_by_time[time_step] = frozenset(current)
    return reachable_by_time
