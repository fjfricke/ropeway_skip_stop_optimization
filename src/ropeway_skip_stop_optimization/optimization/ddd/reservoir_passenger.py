from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import heapq
from time import perf_counter
from typing import Mapping

import gurobipy as gp
from gurobipy import GRB

from ropeway_skip_stop_optimization.optimization.ddd.anonymous_reservoir_network import (
    DddAnonymousReservoirArc,
    DddAnonymousReservoirNetwork,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_network import (
    DddArcFlowBuildTimeLimitError,
)
from ropeway_skip_stop_optimization.optimization.ddd.models import DddRouteDecision
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_arc_flow_problem import (
    DddReservoirArcFlowProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_seconds_to_tick,
    ddd_tick_to_seconds,
)


@dataclass(frozen=True, order=True, slots=True)
class DddReservoirPassengerEvent:
    demand_group_id: str
    arc_id: str
    event_tick: int


@dataclass(frozen=True, slots=True)
class DddReservoirPassengerDomain:
    problem_fingerprint: str
    network_fingerprint: str
    allowed_arc_ids_by_group: tuple[tuple[str, tuple[str, ...]], ...]
    board_events: tuple[DddReservoirPassengerEvent, ...]
    alight_events: tuple[DddReservoirPassengerEvent, ...]

    @property
    def allowed_by_group(self) -> dict[str, tuple[str, ...]]:
        return dict(self.allowed_arc_ids_by_group)

    def validate(
        self,
        problem: DddReservoirArcFlowProblem,
        network: DddAnonymousReservoirNetwork,
    ) -> None:
        if self.problem_fingerprint != problem.fingerprint:
            raise ValueError("reservoir Passenger domain belongs to another problem")
        if self.network_fingerprint != network.fingerprint:
            raise ValueError("reservoir Passenger domain belongs to another network")
        known_groups = {group.id for group in problem.demand_groups}
        known_arcs = {arc.id for arc in network.movement_arcs}
        if set(self.allowed_by_group) != known_groups:
            raise ValueError("reservoir Passenger groups are incomplete")
        if any(
            not set(arc_ids) <= known_arcs
            for _, arc_ids in self.allowed_arc_ids_by_group
        ):
            raise ValueError("reservoir Passenger flow references a non-movement arc")
        keys = tuple(
            (kind, event.demand_group_id, event.arc_id)
            for kind, events in (("b", self.board_events), ("a", self.alight_events))
            for event in events
        )
        if len(keys) != len(set(keys)):
            raise ValueError("reservoir Passenger events must be unique")


@dataclass(frozen=True, slots=True)
class DddReservoirPassengerDomainBuilder:
    def build(
        self,
        problem: DddReservoirArcFlowProblem,
        network: DddAnonymousReservoirNetwork,
        *,
        active_movement_arc_ids: frozenset[str] | None = None,
        deadline_monotonic: float | None = None,
    ) -> DddReservoirPassengerDomain:
        problem.validate()
        network.validate(problem)
        option_by_id = {
            option.id: option for option in problem.movement_core.route_options
        }
        node_by_id = network.node_by_id
        arc_by_id = network.arc_by_id
        outgoing: dict[str, list[DddAnonymousReservoirArc]] = defaultdict(list)
        movement_arcs = tuple(
            arc
            for arc in network.movement_arcs
            if active_movement_arc_ids is None or arc.id in active_movement_arc_ids
        )
        if active_movement_arc_ids is not None and (
            active_movement_arc_ids - {arc.id for arc in network.movement_arcs}
        ):
            raise ValueError("restricted Passenger domain references unknown arcs")
        for arc in movement_arcs:
            assert arc.source_node_id is not None
            outgoing[arc.source_node_id].append(arc)
        station_by_state: dict[str, str] = {}
        for option in problem.movement_core.route_options:
            prior = station_by_state.setdefault(option.from_state_id, option.station_id)
            if prior != option.station_id:
                raise ValueError("reservoir Passenger v1 needs one station per state")
        allowed = []
        board_events = []
        alight_events = []
        for group in sorted(problem.demand_groups, key=lambda item: item.id):
            _check_deadline(deadline_monotonic)
            release_tick = problem.service_start_tick + ddd_seconds_to_tick(
                group.release_time_seconds
            )
            board_arcs = []
            for arc in movement_arcs:
                assert arc.option_id is not None
                option = option_by_id[arc.option_id]
                if (
                    option.station_id != group.origin_station_id
                    or option.decision is not DddRouteDecision.STOP
                    or option.platform_exit_offset_seconds is None
                ):
                    continue
                event_tick = (
                    arc.source_tick
                    + ddd_seconds_to_tick(option.platform_exit_offset_seconds)
                    + arc.wait_tick
                )
                if not release_tick <= event_tick <= problem.service_end_tick:
                    continue
                board_arcs.append(arc)
                board_events.append(
                    DddReservoirPassengerEvent(group.id, arc.id, event_tick)
                )
            group_allowed = _reachable_direct_ride_arcs(
                board_arcs=tuple(board_arcs),
                outgoing_by_node=outgoing,
                station_by_state=station_by_state,
                origin_station_id=group.origin_station_id,
                destination_station_id=group.destination_station_id,
                node_by_id=node_by_id,
            )
            allowed.append((group.id, tuple(sorted(group_allowed))))
            destination_nodes = {
                arc_by_id[arc_id].target_node_id
                for arc_id in group_allowed
                if arc_by_id[arc_id].target_node_id is not None
                and station_by_state[arc_by_id[arc_id].target_state_id]
                == group.destination_station_id
            }
            for node_id in sorted(destination_nodes):
                for arc in sorted(outgoing.get(node_id, ()), key=lambda item: item.id):
                    assert arc.option_id is not None
                    option = option_by_id[arc.option_id]
                    if (
                        option.decision is not DddRouteDecision.STOP
                        or option.platform_entry_offset_seconds is None
                    ):
                        continue
                    event_tick = arc.source_tick + ddd_seconds_to_tick(
                        option.platform_entry_offset_seconds
                    )
                    if event_tick <= problem.service_end_tick:
                        alight_events.append(
                            DddReservoirPassengerEvent(group.id, arc.id, event_tick)
                        )
        result = DddReservoirPassengerDomain(
            problem_fingerprint=problem.fingerprint,
            network_fingerprint=network.fingerprint,
            allowed_arc_ids_by_group=tuple(allowed),
            board_events=tuple(sorted(board_events)),
            alight_events=tuple(sorted(alight_events)),
        )
        result.validate(problem, network)
        return result


@dataclass(slots=True)
class DddReservoirPassengerModel:
    domain: DddReservoirPassengerDomain
    onboard_by_group_arc: dict[tuple[str, str], gp.Var]
    board_by_group_arc: dict[tuple[str, str], gp.Var]
    alight_by_group_arc: dict[tuple[str, str], gp.Var]
    unserved_by_group: dict[str, gp.Var]
    constraint_count: int

    @property
    def variable_count(self) -> int:
        return (
            len(self.onboard_by_group_arc)
            + len(self.board_by_group_arc)
            + len(self.alight_by_group_arc)
            + len(self.unserved_by_group)
        )

    @property
    def total_unserved_expression(self) -> gp.LinExpr:
        return gp.quicksum(self.unserved_by_group.values())

    def journey_time_expression(
        self,
        problem: DddReservoirArcFlowProblem,
    ) -> gp.LinExpr:
        group_by_id = {group.id: group for group in problem.demand_groups}
        event_by_key = {
            (event.demand_group_id, event.arc_id): event
            for event in self.domain.alight_events
        }
        return gp.quicksum(
            (
                ddd_tick_to_seconds(event_by_key[key].event_tick)
                - problem.service_start_seconds
                - group_by_id[key[0]].release_time_seconds
            )
            * variable
            for key, variable in self.alight_by_group_arc.items()
        )

    def set_zero_start(self) -> None:
        for variable in (
            *self.onboard_by_group_arc.values(),
            *self.board_by_group_arc.values(),
            *self.alight_by_group_arc.values(),
        ):
            variable.Start = 0.0


@dataclass(frozen=True, slots=True)
class DddReservoirPassengerModelBuilder:
    integer_assignment: bool = True

    def build(
        self,
        *,
        model: gp.Model,
        problem: DddReservoirArcFlowProblem,
        network: DddAnonymousReservoirNetwork,
        route_by_arc_id: Mapping[str, gp.Var],
        active_movement_arc_ids: frozenset[str] | None = None,
        deadline_monotonic: float | None = None,
    ) -> DddReservoirPassengerModel:
        domain = DddReservoirPassengerDomainBuilder().build(
            problem,
            network,
            active_movement_arc_ids=active_movement_arc_ids,
            deadline_monotonic=deadline_monotonic,
        )
        group_by_id = {group.id: group for group in problem.demand_groups}
        variable_type = GRB.INTEGER if self.integer_assignment else GRB.CONTINUOUS
        onboard: dict[tuple[str, str], gp.Var] = {}
        variable_index = 0
        for group_id, arc_ids in domain.allowed_arc_ids_by_group:
            _check_deadline(deadline_monotonic)
            for arc_id in arc_ids:
                onboard[group_id, arc_id] = model.addVar(
                    lb=0.0,
                    ub=float(group_by_id[group_id].count),
                    vtype=variable_type,
                    name=f"reservoir_onboard[{variable_index}]",
                )
                variable_index += 1
        board = {
            (event.demand_group_id, event.arc_id): model.addVar(
                lb=0.0,
                ub=float(group_by_id[event.demand_group_id].count),
                vtype=variable_type,
                name=f"reservoir_board[{index}]",
            )
            for index, event in enumerate(domain.board_events)
        }
        alight = {
            (event.demand_group_id, event.arc_id): model.addVar(
                lb=0.0,
                ub=float(group_by_id[event.demand_group_id].count),
                vtype=variable_type,
                name=f"reservoir_alight[{index}]",
            )
            for index, event in enumerate(domain.alight_events)
        }
        unserved = {
            group.id: model.addVar(
                lb=0.0,
                ub=float(group.count),
                vtype=variable_type,
                name=f"reservoir_unserved[{group.id}]",
            )
            for group in problem.demand_groups
        }
        model.update()
        count = 0
        incoming: dict[str, list[DddAnonymousReservoirArc]] = defaultdict(list)
        outgoing: dict[str, list[DddAnonymousReservoirArc]] = defaultdict(list)
        for arc in network.movement_arcs:
            if (
                active_movement_arc_ids is not None
                and arc.id not in active_movement_arc_ids
            ):
                continue
            assert arc.source_node_id is not None and arc.target_node_id is not None
            outgoing[arc.source_node_id].append(arc)
            incoming[arc.target_node_id].append(arc)
        arc_by_id = network.arc_by_id
        board_by_node: dict[tuple[str, str], list[gp.Var]] = defaultdict(list)
        alight_by_node: dict[tuple[str, str], list[gp.Var]] = defaultdict(list)
        for (group_id, arc_id), variable in board.items():
            node_id = arc_by_id[arc_id].source_node_id
            assert node_id is not None
            board_by_node[group_id, node_id].append(variable)
        for (group_id, arc_id), variable in alight.items():
            node_id = arc_by_id[arc_id].source_node_id
            assert node_id is not None
            alight_by_node[group_id, node_id].append(variable)
        for group_id, arc_ids in domain.allowed_arc_ids_by_group:
            _check_deadline(deadline_monotonic)
            allowed = set(arc_ids)
            relevant_node_ids = {
                node_id
                for arc_id in allowed
                for node_id in (
                    arc_by_id[arc_id].source_node_id,
                    arc_by_id[arc_id].target_node_id,
                )
                if node_id is not None
            }
            relevant_node_ids.update(
                node_id
                for candidate_group, node_id in (*board_by_node, *alight_by_node)
                if candidate_group == group_id
            )
            for node_id in sorted(relevant_node_ids):
                node_in = tuple(
                    onboard[group_id, arc.id]
                    for arc in incoming.get(node_id, ())
                    if arc.id in allowed
                )
                node_out = tuple(
                    onboard[group_id, arc.id]
                    for arc in outgoing.get(node_id, ())
                    if arc.id in allowed
                )
                node_board = tuple(board_by_node.get((group_id, node_id), ()))
                node_alight = tuple(alight_by_node.get((group_id, node_id), ()))
                if node_in or node_out or node_board or node_alight:
                    model.addConstr(
                        gp.quicksum(node_in) + gp.quicksum(node_board)
                        == gp.quicksum(node_out) + gp.quicksum(node_alight),
                        name=f"reservoir_passenger_flow[{count}]",
                    )
                    count += 1
            group_board = tuple(
                variable
                for (candidate, _), variable in board.items()
                if candidate == group_id
            )
            group_alight = tuple(
                variable
                for (candidate, _), variable in alight.items()
                if candidate == group_id
            )
            model.addConstr(
                gp.quicksum(group_board) + unserved[group_id]
                == group_by_id[group_id].count,
                name=f"reservoir_passenger_demand[{group_id}]",
            )
            model.addConstr(
                gp.quicksum(group_board) == gp.quicksum(group_alight),
                name=f"reservoir_passenger_balance[{group_id}]",
            )
            count += 2
        for (group_id, arc_id), variable in (*board.items(), *alight.items()):
            model.addConstr(
                variable <= group_by_id[group_id].count * route_by_arc_id[arc_id],
                name=f"reservoir_passenger_activation[{count}]",
            )
            count += 1
        onboard_by_arc: dict[str, list[gp.Var]] = defaultdict(list)
        for (_, arc_id), variable in onboard.items():
            onboard_by_arc[arc_id].append(variable)
        for arc_id, values in onboard_by_arc.items():
            if count % 10_000 == 0:
                _check_deadline(deadline_monotonic)
            model.addConstr(
                gp.quicksum(values) <= problem.cabin_capacity * route_by_arc_id[arc_id],
                name=f"reservoir_passenger_capacity[{count}]",
            )
            count += 1
        model.update()
        return DddReservoirPassengerModel(
            domain=domain,
            onboard_by_group_arc=onboard,
            board_by_group_arc=board,
            alight_by_group_arc=alight,
            unserved_by_group=unserved,
            constraint_count=count,
        )


def _reachable_direct_ride_arcs(
    *,
    board_arcs: tuple[DddAnonymousReservoirArc, ...],
    outgoing_by_node: Mapping[str, list[DddAnonymousReservoirArc]],
    station_by_state: Mapping[str, str],
    origin_station_id: str,
    destination_station_id: str,
    node_by_id: Mapping[str, object],
) -> set[str]:
    allowed = {arc.id for arc in board_arcs}
    frontier = [
        arc.target_node_id for arc in board_arcs if arc.target_node_id is not None
    ]
    heapq.heapify(frontier)
    queued = set(frontier)
    visited: set[str] = set()
    while frontier:
        node_id = heapq.heappop(frontier)
        queued.discard(node_id)
        if node_id in visited:
            continue
        visited.add(node_id)
        node = node_by_id[node_id]
        station_id = station_by_state[node.state_id]
        if station_id in {origin_station_id, destination_station_id}:
            continue
        for arc in outgoing_by_node.get(node_id, ()):
            assert arc.target_state_id is not None
            target_station = station_by_state[arc.target_state_id]
            if target_station == origin_station_id:
                continue
            allowed.add(arc.id)
            if (
                arc.target_node_id is not None
                and arc.target_node_id not in visited
                and arc.target_node_id not in queued
            ):
                heapq.heappush(frontier, arc.target_node_id)
                queued.add(arc.target_node_id)
    return allowed


def _check_deadline(deadline_monotonic: float | None) -> None:
    if deadline_monotonic is not None and perf_counter() >= deadline_monotonic:
        raise DddArcFlowBuildTimeLimitError(
            "reservoir arc-flow budget expired during Passenger model construction"
        )
