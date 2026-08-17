from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddMovementProblem,
    DddRouteDecision,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_model import (
    DddLayeredTimeArc,
    DddLayeredTimeArcKind,
    DddLayeredTimeNetwork,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_seconds_to_tick,
    ddd_tick_to_seconds,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    expand_demands_to_ean_groups,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.fixed_movement_passenger_model import (
    EanPassengerAssignmentDomain,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_objective import (
    EanPassengerObjective,
    EanPassengerObjectiveEvent,
    ean_passenger_objective_definition,
)


@dataclass(frozen=True)
class DddPassengerMasterProblem:
    """Passenger relaxation coupled to an anonymous DDD movement network."""

    movement_problem: DddMovementProblem
    demand_groups: tuple[EanDemandGroup, ...]
    cabin_capacity: int
    objective: EanPassengerObjective
    assignment_domain: EanPassengerAssignmentDomain = (
        EanPassengerAssignmentDomain.LP_RELAXATION
    )

    def validate(self) -> None:
        self.movement_problem.validate()
        if self.cabin_capacity <= 0:
            raise ValueError("DDD passenger master cabin capacity must be positive")
        if not isinstance(self.objective, EanPassengerObjective):
            raise ValueError("DDD passenger master objective is invalid")
        if not isinstance(self.assignment_domain, EanPassengerAssignmentDomain):
            raise ValueError("DDD passenger assignment domain is invalid")
        group_ids: set[str] = set()
        for group in self.demand_groups:
            group.validate()
            if group.id in group_ids:
                raise ValueError(f"duplicate DDD passenger demand group: {group.id}")
            group_ids.add(group.id)


def build_ddd_passenger_master_problem(
    *,
    scenario: Scenario,
    artifact: EanBuildArtifact,
    movement_problem: DddMovementProblem,
    objective: EanPassengerObjective,
    assignment_domain: EanPassengerAssignmentDomain = (
        EanPassengerAssignmentDomain.LP_RELAXATION
    ),
) -> DddPassengerMasterProblem:
    if scenario.id != artifact.scenario_id:
        raise ValueError("DDD passenger master scenario and artifact differ")
    if movement_problem.scenario_id != artifact.scenario_id:
        raise ValueError("DDD passenger master movement and artifact differ")
    result = DddPassengerMasterProblem(
        movement_problem=movement_problem,
        demand_groups=expand_demands_to_ean_groups(scenario),
        cabin_capacity=artifact.config.cabin_capacity,
        objective=objective,
        assignment_domain=assignment_domain,
    )
    result.validate()
    return result


@dataclass(frozen=True)
class DddPassengerArcValue:
    demand_group_id: str
    arc_id: str
    value: float


@dataclass(frozen=True)
class DddPassengerServiceValue:
    demand_group_id: str
    arc_id: str
    value: float


@dataclass(frozen=True)
class DddPassengerMasterSolution:
    onboard_values: tuple[DddPassengerArcValue, ...]
    board_values: tuple[DddPassengerServiceValue, ...]
    alight_values: tuple[DddPassengerServiceValue, ...]
    variable_count: int
    constraint_count: int
    served_passenger_count: float
    unserved_passenger_count: float


@dataclass(frozen=True)
class DddPassengerMasterModel:
    problem: DddPassengerMasterProblem
    onboard: dict[tuple[str, str], Any]
    board: dict[tuple[str, str], Any]
    alight: dict[tuple[str, str], Any]
    constraint_count: int

    @property
    def variable_count(self) -> int:
        return len(self.onboard) + len(self.board) + len(self.alight)

    def extract_solution(self, *, tolerance: float = 1e-7) -> DddPassengerMasterSolution:
        onboard_values = tuple(
            DddPassengerArcValue(group_id, arc_id, float(variable.X))
            for (group_id, arc_id), variable in sorted(self.onboard.items())
            if variable.X > tolerance
        )
        board_values = tuple(
            DddPassengerServiceValue(group_id, arc_id, float(variable.X))
            for (group_id, arc_id), variable in sorted(self.board.items())
            if variable.X > tolerance
        )
        alight_values = tuple(
            DddPassengerServiceValue(group_id, arc_id, float(variable.X))
            for (group_id, arc_id), variable in sorted(self.alight.items())
            if variable.X > tolerance
        )
        served = sum(item.value for item in board_values)
        total = sum(group.count for group in self.problem.demand_groups)
        return DddPassengerMasterSolution(
            onboard_values=onboard_values,
            board_values=board_values,
            alight_values=alight_values,
            variable_count=self.variable_count,
            constraint_count=self.constraint_count,
            served_passenger_count=served,
            unserved_passenger_count=max(0.0, total - served),
        )


def add_ddd_passenger_master(
    *,
    model: Any,
    gp: Any,
    grb: Any,
    network: DddLayeredTimeNetwork,
    movement_flow_variables: dict[str, Any],
    problem: DddPassengerMasterProblem,
) -> DddPassengerMasterModel:
    """Add an optimistic direct-service multicommodity flow to a DDD master.

    Passenger flow may re-pair anonymous cabin capacity inside one coarse DDD
    cell.  That enlarges the feasible set and is therefore admissible only as
    a lower-bound relaxation.  A physical passenger plan is always recovered
    later on a completely validated movement plan.
    """

    network.validate()
    problem.validate()
    movement = problem.movement_problem
    if set(network.cabin_ids) != {start.cabin_id for start in movement.starts}:
        raise ValueError("DDD passenger master network and movement starts differ")
    option_by_id = {option.id: option for option in movement.route_options}
    node_by_id = {node.id: node for node in network.nodes}
    arc_by_id = network.arcs_by_id
    movement_arcs = tuple(
        arc
        for arc in network.arcs
        if arc.kind in (
            DddLayeredTimeArcKind.SOURCE,
            DddLayeredTimeArcKind.MOVEMENT,
        )
        and arc.partial_arc is not None
    )
    outgoing_by_node: dict[str, list[DddLayeredTimeArc]] = {
        node.id: [] for node in network.nodes
    }
    incoming_by_node: dict[str, list[DddLayeredTimeArc]] = {
        node.id: [] for node in network.nodes
    }
    for arc in movement_arcs:
        if arc.source_node_id is not None:
            outgoing_by_node[arc.source_node_id].append(arc)
        if arc.target_node_id is not None:
            incoming_by_node[arc.target_node_id].append(arc)
    station_by_node_id: dict[str, str] = {}
    for node_id, arcs in outgoing_by_node.items():
        station_ids = {
            option_by_id[arc.partial_arc.route_option_id].station_id
            for arc in arcs
            if arc.partial_arc is not None
        }
        if len(station_ids) > 1:
            raise ValueError(
                "DDD passenger master v1 requires one physical station per state"
            )
        if station_ids:
            station_by_node_id[node_id] = next(iter(station_ids))

    variable_type = (
        grb.INTEGER
        if problem.assignment_domain is EanPassengerAssignmentDomain.INTEGER
        else grb.CONTINUOUS
    )
    onboard: dict[tuple[str, str], Any] = {}
    onboard_by_arc_id: dict[str, list[Any]] = {
        arc.id: [] for arc in movement_arcs
    }
    board: dict[tuple[str, str], Any] = {}
    alight: dict[tuple[str, str], Any] = {}
    constraint_count = 0
    objective_definition = ean_passenger_objective_definition(problem.objective)
    objective_constant = 0.0

    starts_by_cabin_id = {start.cabin_id: start for start in movement.starts}

    for group in problem.demand_groups:
        group_objective_terms: list[tuple[float, Any]] = []
        group_board: list[Any] = []
        group_alight: list[Any] = []
        release_tick = ddd_seconds_to_tick(group.release_time_seconds)
        service_end_tick = movement.passenger_service_end_tick
        board_arcs = tuple(
            arc
            for arc in movement_arcs
            if _arc_station_id(arc, option_by_id) == group.origin_station_id
            and _arc_is_stop(arc, option_by_id)
            and _boarding_window_intersects_service(
                arc,
                option_by_id=option_by_id,
                node_by_id=node_by_id,
                starts_by_cabin_id=starts_by_cabin_id,
                release_tick=release_tick,
                service_end_tick=service_end_tick,
            )
        )
        allowed_arc_ids = _passenger_reachable_arc_ids(
            board_arcs=board_arcs,
            outgoing_by_node=outgoing_by_node,
            station_by_node_id=station_by_node_id,
            origin_station_id=group.origin_station_id,
            destination_station_id=group.destination_station_id,
        )
        for arc in movement_arcs:
            if arc.id not in allowed_arc_ids:
                continue
            variable = model.addVar(
                lb=0.0,
                ub=float(group.count),
                vtype=variable_type,
                name=f"ddd_passenger_flow[{len(onboard)}]",
            )
            onboard[group.id, arc.id] = variable
            onboard_by_arc_id[arc.id].append(variable)
        for arc in board_arcs:
            if arc.id not in allowed_arc_ids:
                continue
            variable = model.addVar(
                lb=0.0,
                ub=float(group.count),
                vtype=variable_type,
                name=f"ddd_board[{len(board)}]",
            )
            board[group.id, arc.id] = variable
            group_board.append(variable)
            model.addConstr(
                onboard[group.id, arc.id] == variable,
                name=f"ddd_board_flow[{len(board) - 1}]",
            )
            constraint_count += 1
            if objective_definition.event is EanPassengerObjectiveEvent.BOARDING:
                earliest_tick, _ = _arc_source_tick_bounds(
                    arc,
                    node_by_id=node_by_id,
                    starts_by_cabin_id=starts_by_cabin_id,
                )
                option = option_by_id[arc.partial_arc.route_option_id]
                event_tick = max(
                    release_tick,
                    earliest_tick
                    + ddd_seconds_to_tick(option.platform_exit_offset_seconds),
                )
                served_cost = objective_definition.optimistic_served_cost_lower_bound_seconds(
                    release_time_seconds=group.release_time_seconds,
                    earliest_boarding_time_seconds=ddd_tick_to_seconds(event_tick),
                    earliest_alighting_time_seconds=ddd_tick_to_seconds(event_tick),
                )
                group_objective_terms.append((served_cost, variable))

        reachable_target_node_ids = {
            arc_by_id[arc_id].target_node_id
            for arc_id in allowed_arc_ids
            if arc_by_id[arc_id].target_node_id is not None
        }
        destination_nodes = tuple(
            node
            for node in network.nodes
            if node.id in reachable_target_node_ids
            and station_by_node_id.get(node.id) == group.destination_station_id
        )
        for node in destination_nodes:
            stop_arcs = tuple(
                arc
                for arc in outgoing_by_node[node.id]
                if _arc_is_stop(arc, option_by_id)
                and _earliest_alighting_tick(
                    arc,
                    option_by_id=option_by_id,
                    node_by_id=node_by_id,
                    starts_by_cabin_id=starts_by_cabin_id,
                )
                <= service_end_tick
            )
            for arc in stop_arcs:
                variable = model.addVar(
                    lb=0.0,
                    ub=float(group.count),
                    vtype=variable_type,
                    name=f"ddd_alight[{len(alight)}]",
                )
                alight[group.id, arc.id] = variable
                group_alight.append(variable)
                model.addConstr(
                    variable
                    <= problem.cabin_capacity * movement_flow_variables[arc.id],
                    name=f"ddd_alight_activation[{len(alight) - 1}]",
                )
                constraint_count += 1
                if objective_definition.event is EanPassengerObjectiveEvent.ALIGHTING:
                    event_tick = _earliest_alighting_tick(
                        arc,
                        option_by_id=option_by_id,
                        node_by_id=node_by_id,
                        starts_by_cabin_id=starts_by_cabin_id,
                    )
                    served_cost = objective_definition.optimistic_served_cost_lower_bound_seconds(
                        release_time_seconds=group.release_time_seconds,
                        earliest_boarding_time_seconds=group.release_time_seconds,
                        earliest_alighting_time_seconds=ddd_tick_to_seconds(event_tick),
                    )
                    group_objective_terms.append((served_cost, variable))

        for node in network.nodes:
            incoming = tuple(
                onboard[group.id, arc.id]
                for arc in incoming_by_node[node.id]
                if (group.id, arc.id) in onboard
            )
            outgoing = tuple(
                onboard[group.id, arc.id]
                for arc in outgoing_by_node[node.id]
                if (group.id, arc.id) in onboard
            )
            node_alight = tuple(
                alight[group.id, arc.id]
                for arc in outgoing_by_node[node.id]
                if (group.id, arc.id) in alight
            )
            node_board = tuple(
                board[group.id, arc.id]
                for arc in outgoing_by_node[node.id]
                if (group.id, arc.id) in board
            )
            if incoming or outgoing or node_alight or node_board:
                model.addConstr(
                    gp.quicksum(incoming) + gp.quicksum(node_board)
                    == gp.quicksum(outgoing) + gp.quicksum(node_alight),
                    name=f"ddd_passenger_conservation[{constraint_count}]",
                )
                constraint_count += 1

        model.addConstr(
            gp.quicksum(group_board) == gp.quicksum(group_alight),
            name=f"ddd_passenger_balance[{group.id}]",
        )
        model.addConstr(
            gp.quicksum(group_board) <= group.count,
            name=f"ddd_passenger_demand[{group.id}]",
        )
        constraint_count += 2
        unserved_cost = objective_definition.unserved_cost_seconds(
            release_time_seconds=group.release_time_seconds,
            horizon_seconds=movement.passenger_service_end_seconds,
        )
        objective_constant += unserved_cost * group.count
        for served_cost, variable in group_objective_terms:
            model.setAttr("Obj", variable, served_cost - unserved_cost)

    for arc in movement_arcs:
        arc_flows = onboard_by_arc_id[arc.id]
        if not arc_flows:
            continue
        model.addConstr(
            gp.quicksum(arc_flows)
            <= problem.cabin_capacity * movement_flow_variables[arc.id],
            name=f"ddd_passenger_capacity[{constraint_count}]",
        )
        constraint_count += 1

    model.setAttr("ObjCon", objective_constant)
    return DddPassengerMasterModel(
        problem=problem,
        onboard=onboard,
        board=board,
        alight=alight,
        constraint_count=constraint_count,
    )


def _passenger_reachable_arc_ids(
    *,
    board_arcs: tuple[DddLayeredTimeArc, ...],
    outgoing_by_node: dict[str, list[DddLayeredTimeArc]],
    station_by_node_id: dict[str, str],
    origin_station_id: str,
    destination_station_id: str,
) -> set[str]:
    allowed = {arc.id for arc in board_arcs}
    frontier = {
        arc.target_node_id for arc in board_arcs if arc.target_node_id is not None
    }
    visited: set[str] = set()
    while frontier:
        node_id = min(frontier)
        frontier.remove(node_id)
        if node_id in visited:
            continue
        visited.add(node_id)
        station_id = station_by_node_id.get(node_id)
        if station_id in (origin_station_id, destination_station_id):
            continue
        for arc in outgoing_by_node.get(node_id, ()):
            target_station_id = (
                station_by_node_id.get(arc.target_node_id)
                if arc.target_node_id is not None
                else None
            )
            if target_station_id == origin_station_id:
                continue
            allowed.add(arc.id)
            if arc.target_node_id is not None:
                frontier.add(arc.target_node_id)
    return allowed


def _arc_station_id(
    arc: DddLayeredTimeArc,
    option_by_id: dict[str, Any],
) -> str:
    if arc.partial_arc is None:
        raise ValueError("DDD passenger service arc has no route option")
    return option_by_id[arc.partial_arc.route_option_id].station_id


def _arc_is_stop(
    arc: DddLayeredTimeArc,
    option_by_id: dict[str, Any],
) -> bool:
    if arc.partial_arc is None:
        return False
    return (
        option_by_id[arc.partial_arc.route_option_id].decision
        is DddRouteDecision.STOP
    )


def _arc_source_tick_bounds(
    arc: DddLayeredTimeArc,
    *,
    node_by_id: dict[str, Any],
    starts_by_cabin_id: dict[int, Any],
) -> tuple[int, int]:
    if arc.kind is DddLayeredTimeArcKind.SOURCE:
        if arc.cabin_id is None:
            raise ValueError("DDD passenger source arc lacks a cabin start")
        tick = starts_by_cabin_id[arc.cabin_id].time_tick
        return tick, tick
    if arc.source_node_id is None:
        raise ValueError("DDD passenger movement arc lacks a source node")
    cell = node_by_id[arc.source_node_id].cell
    return cell.lower_tick, cell.upper_tick - 1


def _boarding_window_intersects_service(
    arc: DddLayeredTimeArc,
    *,
    option_by_id: dict[str, Any],
    node_by_id: dict[str, Any],
    starts_by_cabin_id: dict[int, Any],
    release_tick: int,
    service_end_tick: int,
) -> bool:
    earliest, latest = _arc_source_tick_bounds(
        arc,
        node_by_id=node_by_id,
        starts_by_cabin_id=starts_by_cabin_id,
    )
    option = option_by_id[arc.partial_arc.route_option_id]
    offset = ddd_seconds_to_tick(option.platform_exit_offset_seconds)
    return latest + offset >= release_tick and earliest + offset <= service_end_tick


def _earliest_alighting_tick(
    arc: DddLayeredTimeArc,
    *,
    option_by_id: dict[str, Any],
    node_by_id: dict[str, Any],
    starts_by_cabin_id: dict[int, Any],
) -> int:
    earliest, _ = _arc_source_tick_bounds(
        arc,
        node_by_id=node_by_id,
        starts_by_cabin_id=starts_by_cabin_id,
    )
    option = option_by_id[arc.partial_arc.route_option_id]
    return earliest + ddd_seconds_to_tick(option.platform_entry_offset_seconds)
