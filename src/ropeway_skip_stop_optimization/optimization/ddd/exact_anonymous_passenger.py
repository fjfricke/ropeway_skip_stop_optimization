from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import heapq
from typing import Mapping

import gurobipy as gp
from gurobipy import GRB

from ropeway_skip_stop_optimization.optimization.ddd.exact_anonymous_arc_flow_network import (
    DddExactAnonymousArc,
    DddExactAnonymousArcFlowNetwork,
    DddExactAnonymousNode,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_preparation import (
    DddPreparedArcFlowProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import (
    DddFixedKTrajectoryProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k_primal_seed import (
    DddFixedKPrimalSeed,
)
from ropeway_skip_stop_optimization.optimization.ddd.models import DddRouteDecision
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_seconds_to_tick,
    ddd_tick_to_seconds,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.fixed_movement_passenger_model import (
    EanPassengerAssignmentDomain,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_objective import (
    EanPassengerObjectiveEvent,
    ean_passenger_objective_definition,
)


@dataclass(frozen=True, order=True, slots=True)
class DddExactAnonymousPassengerEvent:
    demand_group_id: str
    arc_id: str
    event_tick: int
    objective_coefficient: float


@dataclass(frozen=True, slots=True)
class DddExactAnonymousPassengerDomain:
    problem_fingerprint: str
    network_fingerprint: str
    cabin_capacity: int
    objective_constant: float
    allowed_arc_ids_by_group: tuple[tuple[str, tuple[str, ...]], ...]
    board_events: tuple[DddExactAnonymousPassengerEvent, ...]
    alight_events: tuple[DddExactAnonymousPassengerEvent, ...]

    @property
    def allowed_by_group(self) -> dict[str, tuple[str, ...]]:
        return dict(self.allowed_arc_ids_by_group)

    def validate(
        self,
        problem: DddFixedKTrajectoryProblem,
        network: DddExactAnonymousArcFlowNetwork,
    ) -> None:
        if self.problem_fingerprint != problem.fingerprint:
            raise ValueError("exact anonymous Passenger domain and problem differ")
        if self.network_fingerprint != network.fingerprint:
            raise ValueError("exact anonymous Passenger domain and network differ")
        if self.cabin_capacity <= 0 or self.objective_constant < 0:
            raise ValueError("exact anonymous Passenger constants are invalid")
        known_groups = {group.id for group in problem.passenger_build.demand_groups}
        known_arcs = set(network.arc_by_id)
        if set(self.allowed_by_group) != known_groups:
            raise ValueError("exact anonymous Passenger groups are incomplete")
        if any(
            not set(arc_ids) <= known_arcs
            for _, arc_ids in self.allowed_arc_ids_by_group
        ):
            raise ValueError("exact anonymous Passenger flow uses an unknown arc")
        event_keys = tuple(
            (kind, item.demand_group_id, item.arc_id)
            for kind, events in (("b", self.board_events), ("a", self.alight_events))
            for item in events
        )
        if len(set(event_keys)) != len(event_keys):
            raise ValueError("exact anonymous Passenger events must be unique")
        if any(
            item.demand_group_id not in known_groups
            or item.arc_id not in known_arcs
            or item.event_tick < 0
            for item in (*self.board_events, *self.alight_events)
        ):
            raise ValueError("exact anonymous Passenger event is invalid")


@dataclass(frozen=True, slots=True)
class DddExactAnonymousPassengerDomainBuilder:
    """Build exact direct-ride flow on exact state-time nodes."""

    def build(
        self,
        problem: DddFixedKTrajectoryProblem,
        network: DddExactAnonymousArcFlowNetwork,
    ) -> DddExactAnonymousPassengerDomain:
        problem.validate()
        network.validate()
        if network.problem_fingerprint != problem.fingerprint:
            raise ValueError("exact anonymous network belongs to another problem")
        movement = problem.resolved_trajectory_problem.structural_movement_problem
        option_by_id = {option.id: option for option in movement.route_options}
        arc_by_id = network.arc_by_id
        node_by_id = network.node_by_id
        outgoing: dict[str, list[DddExactAnonymousArc]] = defaultdict(list)
        for arc in network.movement_arcs:
            assert arc.source_node_id is not None
            outgoing[arc.source_node_id].append(arc)
        station_by_state: dict[str, str] = {}
        for option in movement.route_options:
            previous = station_by_state.setdefault(
                option.from_state_id, option.station_id
            )
            if previous != option.station_id:
                raise ValueError(
                    "exact anonymous Passenger v1 requires one station per state"
                )
        definition = ean_passenger_objective_definition(problem.objective)
        horizon = problem.artifact.config.horizon_seconds
        service_end = movement.passenger_service_end_tick
        allowed: list[tuple[str, tuple[str, ...]]] = []
        board_events: list[DddExactAnonymousPassengerEvent] = []
        alight_events: list[DddExactAnonymousPassengerEvent] = []
        objective_constant = 0.0
        for group in sorted(
            problem.passenger_build.demand_groups, key=lambda item: item.id
        ):
            release_tick = ddd_seconds_to_tick(group.release_time_seconds)
            unserved = definition.unserved_cost_seconds(
                release_time_seconds=group.release_time_seconds,
                horizon_seconds=horizon,
            )
            objective_constant += group.count * unserved
            group_board_arcs: list[DddExactAnonymousArc] = []
            for arc in network.arcs:
                option = option_by_id[arc.option_id]
                if (
                    option.station_id != group.origin_station_id
                    or option.decision is not DddRouteDecision.STOP
                    or option.platform_exit_offset_seconds is None
                    or arc.target_node_id is None
                ):
                    continue
                event_tick = arc.source_tick + ddd_seconds_to_tick(
                    option.platform_exit_offset_seconds
                ) + arc.wait_tick
                if not release_tick <= event_tick <= service_end:
                    continue
                coefficient = (
                    ddd_tick_to_seconds(event_tick) - horizon
                    if definition.event is EanPassengerObjectiveEvent.BOARDING
                    else 0.0
                )
                board_events.append(
                    DddExactAnonymousPassengerEvent(
                        group.id,
                        arc.id,
                        event_tick,
                        coefficient,
                    )
                )
                group_board_arcs.append(arc)
            group_allowed = _reachable_direct_ride_arcs(
                board_arcs=tuple(group_board_arcs),
                outgoing_by_node=outgoing,
                station_by_state=station_by_state,
                origin_station_id=group.origin_station_id,
                destination_station_id=group.destination_station_id,
                node_by_id=node_by_id,
            )
            allowed.append((group.id, tuple(sorted(group_allowed))))
            reachable_destination_nodes = {
                arc_by_id[arc_id].target_node_id
                for arc_id in group_allowed
                if arc_by_id[arc_id].target_node_id is not None
                and station_by_state[arc_by_id[arc_id].target_state_id]
                == group.destination_station_id
            }
            for node_id in sorted(reachable_destination_nodes):
                for arc in sorted(outgoing.get(node_id, ()), key=lambda item: item.id):
                    option = option_by_id[arc.option_id]
                    if (
                        option.decision is not DddRouteDecision.STOP
                        or option.platform_entry_offset_seconds is None
                    ):
                        continue
                    event_tick = arc.source_tick + ddd_seconds_to_tick(
                        option.platform_entry_offset_seconds
                    )
                    if event_tick > service_end:
                        continue
                    coefficient = (
                        ddd_tick_to_seconds(event_tick) - horizon
                        if definition.event is EanPassengerObjectiveEvent.ALIGHTING
                        else 0.0
                    )
                    alight_events.append(
                        DddExactAnonymousPassengerEvent(
                            group.id,
                            arc.id,
                            event_tick,
                            coefficient,
                        )
                    )
        result = DddExactAnonymousPassengerDomain(
            problem_fingerprint=problem.fingerprint,
            network_fingerprint=network.fingerprint,
            cabin_capacity=int(round(problem.artifact.config.cabin_capacity)),
            objective_constant=objective_constant,
            allowed_arc_ids_by_group=tuple(allowed),
            board_events=tuple(sorted(board_events)),
            alight_events=tuple(sorted(alight_events)),
        )
        result.validate(problem, network)
        return result


@dataclass(slots=True)
class DddExactAnonymousPassengerModel:
    domain: DddExactAnonymousPassengerDomain
    onboard_by_group_arc: dict[tuple[str, str], gp.Var]
    board_by_group_arc: dict[tuple[str, str], gp.Var]
    alight_by_group_arc: dict[tuple[str, str], gp.Var]
    constraint_count: int

    @property
    def variable_count(self) -> int:
        return (
            len(self.onboard_by_group_arc)
            + len(self.board_by_group_arc)
            + len(self.alight_by_group_arc)
        )

    def apply_seed(
        self,
        *,
        problem: DddFixedKTrajectoryProblem,
        prepared: DddPreparedArcFlowProblem,
        network: DddExactAnonymousArcFlowNetwork,
        seed: DddFixedKPrimalSeed,
        labeled_movement_values: Mapping[str, float],
        tolerance: float = 1e-5,
    ) -> float:
        """Project one complete labeled Passenger plan onto exact anonymous flow."""

        seed.validate(problem)
        anonymous_by_labeled = {
            labeled_id: arc.id
            for arc in network.arcs
            for labeled_id in arc.represented_labeled_arc_ids
        }
        selected_by_cabin_visit: dict[tuple[int, int], str] = {}
        for labeled_arc in prepared.arcs:
            if (
                labeled_movement_values[labeled_arc.id] <= 0.5
                or not labeled_arc.source_active
            ):
                continue
            selected_by_cabin_visit[labeled_arc.cabin_id, labeled_arc.visit_index] = (
                anonymous_by_labeled[labeled_arc.id]
            )
        candidate_by_id = {
            candidate.id: candidate
            for candidate in problem.passenger_build.ride_candidates
        }
        onboard_values: dict[tuple[str, str], float] = defaultdict(float)
        board_values: dict[tuple[str, str], float] = defaultdict(float)
        alight_values: dict[tuple[str, str], float] = defaultdict(float)
        for candidate_id, value in seed.ride_counts_by_candidate_id.items():
            candidate = candidate_by_id[candidate_id]
            board_arc_id = selected_by_cabin_visit[
                candidate.cabin_id, candidate.board_visit_index
            ]
            alight_arc_id = selected_by_cabin_visit[
                candidate.cabin_id, candidate.alight_visit_index
            ]
            board_values[candidate.demand_group_id, board_arc_id] += value
            alight_values[candidate.demand_group_id, alight_arc_id] += value
            for visit_index in range(
                candidate.board_visit_index,
                candidate.alight_visit_index,
            ):
                arc_id = selected_by_cabin_visit[candidate.cabin_id, visit_index]
                onboard_values[candidate.demand_group_id, arc_id] += value
        for key, variable in self.onboard_by_group_arc.items():
            variable.Start = onboard_values.get(key, 0.0)
        for key, variable in self.board_by_group_arc.items():
            variable.Start = board_values.get(key, 0.0)
        for key, variable in self.alight_by_group_arc.items():
            variable.Start = alight_values.get(key, 0.0)
        unknown = (
            set(onboard_values) - set(self.onboard_by_group_arc)
            | set(board_values) - set(self.board_by_group_arc)
            | set(alight_values) - set(self.alight_by_group_arc)
        )
        if unknown:
            raise ValueError("Passenger seed is outside the exact anonymous domain")
        event_by_key = {
            (event.demand_group_id, event.arc_id): event
            for event in (*self.domain.board_events, *self.domain.alight_events)
        }
        objective = self.domain.objective_constant + sum(
            event_by_key[key].objective_coefficient * value
            for values in (board_values, alight_values)
            for key, value in values.items()
        )
        if abs(objective - seed.objective_value) > tolerance:
            raise ValueError(
                "exact anonymous Passenger seed objective differs from its certificate"
            )
        return objective


@dataclass(frozen=True, slots=True)
class DddExactAnonymousPassengerModelBuilder:
    def build(
        self,
        *,
        model: gp.Model,
        problem: DddFixedKTrajectoryProblem,
        network: DddExactAnonymousArcFlowNetwork,
        route_by_arc_id: Mapping[str, gp.Var],
        assignment_domain: EanPassengerAssignmentDomain = (
            EanPassengerAssignmentDomain.INTEGER
        ),
    ) -> DddExactAnonymousPassengerModel:
        domain = DddExactAnonymousPassengerDomainBuilder().build(problem, network)
        arc_by_id = network.arc_by_id
        variable_type = (
            GRB.INTEGER
            if assignment_domain is EanPassengerAssignmentDomain.INTEGER
            else GRB.CONTINUOUS
        )
        group_by_id = {
            group.id: group for group in problem.passenger_build.demand_groups
        }
        onboard: dict[tuple[str, str], gp.Var] = {}
        for group_id, arc_ids in domain.allowed_arc_ids_by_group:
            for arc_id in arc_ids:
                onboard[group_id, arc_id] = model.addVar(
                    lb=0.0,
                    ub=float(group_by_id[group_id].count),
                    vtype=variable_type,
                    name=f"exact_onboard[{len(onboard)}]",
                )
        board = {
            (event.demand_group_id, event.arc_id): model.addVar(
                lb=0.0,
                ub=float(group_by_id[event.demand_group_id].count),
                obj=event.objective_coefficient,
                vtype=variable_type,
                name=f"exact_board[{index}]",
            )
            for index, event in enumerate(domain.board_events)
        }
        alight = {
            (event.demand_group_id, event.arc_id): model.addVar(
                lb=0.0,
                ub=float(group_by_id[event.demand_group_id].count),
                obj=event.objective_coefficient,
                vtype=variable_type,
                name=f"exact_alight[{index}]",
            )
            for index, event in enumerate(domain.alight_events)
        }
        model.update()
        count = 0
        incoming: dict[str, list[DddExactAnonymousArc]] = defaultdict(list)
        outgoing: dict[str, list[DddExactAnonymousArc]] = defaultdict(list)
        for arc in network.arcs:
            if arc.target_node_id is not None:
                incoming[arc.target_node_id].append(arc)
            if arc.source_node_id is not None:
                outgoing[arc.source_node_id].append(arc)
        source_arc_ids = {arc.id for arc in network.source_arcs}
        board_by_group_node: dict[tuple[str, str], list[gp.Var]] = defaultdict(list)
        alight_by_group_node: dict[tuple[str, str], list[gp.Var]] = defaultdict(list)
        for (group_id, arc_id), variable in board.items():
            node_id = arc_by_id[arc_id].source_node_id
            if node_id is not None:
                board_by_group_node[group_id, node_id].append(variable)
        for (group_id, arc_id), variable in alight.items():
            node_id = arc_by_id[arc_id].source_node_id
            assert node_id is not None
            alight_by_group_node[group_id, node_id].append(variable)
        for group_id, arc_ids in domain.allowed_arc_ids_by_group:
            allowed_ids = set(arc_ids)
            for arc_id in sorted(allowed_ids & source_arc_ids):
                model.addConstr(
                    onboard[group_id, arc_id] == board[group_id, arc_id],
                    name=f"exact_passenger_source[{count}]",
                )
                count += 1
            for node in network.nodes:
                node_in = tuple(
                    onboard[group_id, arc.id]
                    for arc in incoming.get(node.id, ())
                    if arc.id in allowed_ids
                )
                node_out = tuple(
                    onboard[group_id, arc.id]
                    for arc in outgoing.get(node.id, ())
                    if arc.id in allowed_ids
                )
                node_board = tuple(board_by_group_node.get((group_id, node.id), ()))
                node_alight = tuple(alight_by_group_node.get((group_id, node.id), ()))
                if node_in or node_out or node_board or node_alight:
                    model.addConstr(
                        gp.quicksum(node_in) + gp.quicksum(node_board)
                        == gp.quicksum(node_out) + gp.quicksum(node_alight),
                        name=f"exact_passenger_flow[{count}]",
                    )
                    count += 1
            group_board = tuple(
                variable
                for (candidate_group, _), variable in board.items()
                if candidate_group == group_id
            )
            group_alight = tuple(
                variable
                for (candidate_group, _), variable in alight.items()
                if candidate_group == group_id
            )
            model.addConstr(
                gp.quicksum(group_board) == gp.quicksum(group_alight),
                name=f"exact_passenger_balance[{group_id}]",
            )
            model.addConstr(
                gp.quicksum(group_board) <= group_by_id[group_id].count,
                name=f"exact_passenger_demand[{group_id}]",
            )
            count += 2
        for (group_id, arc_id), variable in (*board.items(), *alight.items()):
            model.addConstr(
                variable <= group_by_id[group_id].count * route_by_arc_id[arc_id],
                name=f"exact_passenger_activation[{count}]",
            )
            count += 1
        onboard_by_arc: dict[str, list[gp.Var]] = defaultdict(list)
        for (_, arc_id), variable in onboard.items():
            onboard_by_arc[arc_id].append(variable)
        for arc in network.arcs:
            arc_flow = tuple(onboard_by_arc.get(arc.id, ()))
            if not arc_flow:
                continue
            model.addConstr(
                gp.quicksum(arc_flow)
                <= domain.cabin_capacity * route_by_arc_id[arc.id],
                name=f"exact_passenger_capacity[{count}]",
            )
            count += 1
        model.ObjCon = domain.objective_constant
        model.update()
        return DddExactAnonymousPassengerModel(
            domain=domain,
            onboard_by_group_arc=onboard,
            board_by_group_arc=board,
            alight_by_group_arc=alight,
            constraint_count=count,
        )


def _reachable_direct_ride_arcs(
    *,
    board_arcs: tuple[DddExactAnonymousArc, ...],
    outgoing_by_node: Mapping[str, list[DddExactAnonymousArc]],
    station_by_state: Mapping[str, str],
    origin_station_id: str,
    destination_station_id: str,
    node_by_id: Mapping[str, DddExactAnonymousNode],
) -> set[str]:
    allowed = {arc.id for arc in board_arcs}
    initial = {
        arc.target_node_id for arc in board_arcs if arc.target_node_id is not None
    }
    frontier = list(initial)
    heapq.heapify(frontier)
    queued = set(initial)
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
            if arc.target_node_id is None:
                continue
            target_station = station_by_state[arc.target_state_id]
            if target_station == origin_station_id:
                continue
            allowed.add(arc.id)
            if arc.target_node_id not in visited and arc.target_node_id not in queued:
                heapq.heappush(frontier, arc.target_node_id)
                queued.add(arc.target_node_id)
    return allowed
