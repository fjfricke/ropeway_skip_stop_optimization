from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import math

import gurobipy as gp
from gurobipy import GRB

from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddMovementProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.support_master import (
    DddSupportConflictCut,
    DddSupportLiteral,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_space import (
    DddPartialTimedArc,
    DddPartialTimedPath,
    DddPartialTimeProblem,
    DddRouteOptionCost,
    DddTerminalThresholdCost,
    DddTimeCell,
    DddTimeDiscretization,
    DddTimeSpaceObjective,
    ddd_normalize_time_seconds,
    ddd_partial_arc_is_compatible,
)


@dataclass(frozen=True)
class DddNetworkTimeObjective:
    route_option_costs: tuple[DddRouteOptionCost, ...]
    terminal_costs: tuple[DddTerminalThresholdCost, ...] = ()
    default_terminal_cost: float = 0.0

    def validate(self, problem: DddMovementProblem) -> None:
        if not math.isfinite(self.default_terminal_cost):
            raise ValueError("DDD default terminal cost must be finite")
        known_option_ids = {option.id for option in problem.route_options}
        route_cost_ids: set[str] = set()
        for item in self.route_option_costs:
            item.validate()
            if item.route_option_id in route_cost_ids:
                raise ValueError(
                    f"duplicate DDD route option cost: {item.route_option_id}"
                )
            if item.route_option_id not in known_option_ids:
                raise ValueError(
                    f"DDD objective references unknown route: {item.route_option_id}"
                )
            route_cost_ids.add(item.route_option_id)
        if route_cost_ids != known_option_ids:
            raise ValueError("DDD objective must price every route option explicitly")

        known_state_ids = {state.id for state in problem.states}
        terminal_state_ids: set[str] = set()
        for item in self.terminal_costs:
            item.validate()
            if item.state_id in terminal_state_ids:
                raise ValueError(f"duplicate DDD terminal cost: {item.state_id}")
            if item.state_id not in known_state_ids:
                raise ValueError(
                    f"DDD terminal objective references unknown state: {item.state_id}"
                )
            terminal_state_ids.add(item.state_id)

    @property
    def route_cost_by_option_id(self) -> dict[str, float]:
        return {item.route_option_id: item.cost for item in self.route_option_costs}

    @property
    def terminal_cost_by_state_id(self) -> dict[str, DddTerminalThresholdCost]:
        return {item.state_id: item for item in self.terminal_costs}

    def terminal_lower_bound(
        self,
        cell: DddTimeCell,
        *,
        tolerance_seconds: float,
    ) -> float:
        terminal_cost = self.terminal_cost_by_state_id.get(cell.state_id)
        if terminal_cost is None:
            return self.default_terminal_cost
        return terminal_cost.lower_bound(
            cell,
            tolerance_seconds=tolerance_seconds,
        )

    def exact_value(
        self,
        route_option_ids: tuple[str, ...],
        terminal_state_id: str,
        terminal_time_seconds: float,
        *,
        tolerance_seconds: float,
    ) -> float:
        route_cost = sum(
            self.route_cost_by_option_id[option_id]
            for option_id in route_option_ids
        )
        terminal_cost = self.terminal_cost_by_state_id.get(terminal_state_id)
        if terminal_cost is None:
            return route_cost + self.default_terminal_cost
        return route_cost + terminal_cost.exact_value(
            terminal_time_seconds,
            tolerance_seconds=tolerance_seconds,
        )


@dataclass(frozen=True)
class DddNetworkTimeProblem:
    movement_problem: DddMovementProblem
    discretization: DddTimeDiscretization
    objective: DddNetworkTimeObjective

    def validate(self) -> None:
        self.movement_problem.validate()
        self.discretization.validate()
        operational_end = ddd_normalize_time_seconds(
            self.movement_problem.operational_end_seconds
        )
        required_sentinel_lower_bound = ddd_normalize_time_seconds(
            operational_end
            + max(
                option.duration_seconds
                for option in self.movement_problem.route_options
            )
        )
        target_state_ids = {
            option.to_state_id for option in self.movement_problem.route_options
        }
        missing = target_state_ids - set(self.discretization.by_state_id)
        if missing:
            raise ValueError(f"DDD target states lack time partitions: {missing}")
        for partition in self.discretization.partitions:
            normalized_boundaries = tuple(
                ddd_normalize_time_seconds(value)
                for value in partition.boundaries_seconds
            )
            if normalized_boundaries[0] != 0.0:
                raise ValueError(
                    f"DDD partition {partition.state_id!r} must start at zero"
                )
            if operational_end not in normalized_boundaries:
                raise ValueError(
                    f"DDD partition {partition.state_id!r} must contain the "
                    "operational horizon boundary"
                )
            if normalized_boundaries[-1] <= required_sentinel_lower_bound:
                raise ValueError(
                    f"DDD partition {partition.state_id!r} sentinel must exceed "
                    "the latest attainable completion"
                )
        self.objective.validate(self.movement_problem)

    def with_discretization(
        self,
        discretization: DddTimeDiscretization,
    ) -> DddNetworkTimeProblem:
        result = DddNetworkTimeProblem(
            movement_problem=self.movement_problem,
            discretization=discretization,
            objective=self.objective,
        )
        result.validate()
        return result


@dataclass(frozen=True, order=True)
class DddLayeredTimeNode:
    layer_index: int
    state_id: str
    cell: DddTimeCell

    def validate(self) -> None:
        if self.layer_index <= 0:
            raise ValueError("DDD layered node index must be positive")
        if self.state_id != self.cell.state_id:
            raise ValueError("DDD layered node and time cell states differ")
        self.cell.validate()

    @property
    def id(self) -> str:
        return f"partial_node::v{self.layer_index}::{self.cell.id}"


class DddLayeredTimeArcKind(StrEnum):
    SOURCE = "source"
    MOVEMENT = "movement"
    SINK = "sink"


@dataclass(frozen=True)
class DddLayeredTimeArc:
    id: str
    kind: DddLayeredTimeArcKind
    source_node_id: str | None
    target_node_id: str | None
    cabin_id: int | None
    partial_arc: DddPartialTimedArc | None
    lower_bound_cost: float

    def validate(self) -> None:
        if not self.id.strip() or not math.isfinite(self.lower_bound_cost):
            raise ValueError("DDD layered arc id and cost must be valid")
        if self.kind is DddLayeredTimeArcKind.SOURCE:
            if (
                self.source_node_id is not None
                or self.target_node_id is None
                or self.cabin_id is None
                or self.partial_arc is None
            ):
                raise ValueError("DDD source arc fields are inconsistent")
        elif self.kind is DddLayeredTimeArcKind.MOVEMENT:
            if (
                self.source_node_id is None
                or self.target_node_id is None
                or self.cabin_id is not None
                or self.partial_arc is None
            ):
                raise ValueError("DDD movement arc fields are inconsistent")
        elif self.kind is DddLayeredTimeArcKind.SINK:
            if (
                self.source_node_id is None
                or self.target_node_id is not None
                or self.cabin_id is not None
                or self.partial_arc is not None
            ):
                raise ValueError("DDD sink arc fields are inconsistent")
        else:
            raise ValueError("DDD layered arc kind is invalid")


@dataclass(frozen=True)
class DddLayeredTimeNetwork:
    nodes: tuple[DddLayeredTimeNode, ...]
    arcs: tuple[DddLayeredTimeArc, ...]
    cabin_ids: tuple[int, ...]

    def validate(self) -> None:
        node_ids = [node.id for node in self.nodes]
        arc_ids = [arc.id for arc in self.arcs]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("duplicate DDD layered node ids")
        if len(arc_ids) != len(set(arc_ids)):
            raise ValueError("duplicate DDD layered arc ids")
        if not self.cabin_ids or len(self.cabin_ids) != len(set(self.cabin_ids)):
            raise ValueError("DDD layered network cabin ids must be unique")
        known_node_ids = set(node_ids)
        source_cabin_ids: set[int] = set()
        for node in self.nodes:
            node.validate()
        for arc in self.arcs:
            arc.validate()
            if (
                arc.source_node_id is not None
                and arc.source_node_id not in known_node_ids
            ) or (
                arc.target_node_id is not None
                and arc.target_node_id not in known_node_ids
            ):
                raise ValueError("DDD layered arc references an unknown node")
            if arc.cabin_id is not None:
                source_cabin_ids.add(arc.cabin_id)
        unknown_source_cabins = source_cabin_ids - set(self.cabin_ids)
        if unknown_source_cabins:
            raise ValueError(
                f"DDD source arcs reference unknown cabins: {unknown_source_cabins}"
            )

    @property
    def arcs_by_id(self) -> dict[str, DddLayeredTimeArc]:
        return {arc.id: arc for arc in self.arcs}


@dataclass(frozen=True)
class DddLayeredTimeNetworkBuilder:
    tolerance_seconds: float = 1e-9

    def build(self, problem: DddNetworkTimeProblem) -> DddLayeredTimeNetwork:
        problem.validate()
        if self.tolerance_seconds < 0:
            raise ValueError("DDD network builder tolerance must be nonnegative")
        movement = problem.movement_problem
        options_by_state = movement.route_options_by_state_id
        route_costs = problem.objective.route_cost_by_option_id
        max_layer = max(start.max_visit_count for start in movement.starts)
        nodes_by_id: dict[str, DddLayeredTimeNode] = {}
        arcs_by_id: dict[str, DddLayeredTimeArc] = {}
        reachable_by_layer: dict[int, set[str]] = {}

        def add_node(node: DddLayeredTimeNode) -> None:
            nodes_by_id[node.id] = node
            reachable_by_layer.setdefault(node.layer_index, set()).add(node.id)

        for start in sorted(movement.starts, key=lambda item: item.cabin_id):
            for option in options_by_state.get(start.state_id, ()):
                for target_cell in problem.discretization.partition(
                    option.to_state_id
                ).cells:
                    if not ddd_partial_arc_is_compatible(
                        source_cell=None,
                        fixed_source_time=start.time_seconds,
                        target_cell=target_cell,
                        option=option,
                        operational_end_seconds=movement.operational_end_seconds,
                        tolerance_seconds=self.tolerance_seconds,
                    ):
                        continue
                    node = DddLayeredTimeNode(1, option.to_state_id, target_cell)
                    add_node(node)
                    partial_arc = DddPartialTimedArc(
                        visit_index=0,
                        route_option_id=option.id,
                        from_state_id=option.from_state_id,
                        to_state_id=option.to_state_id,
                        source_cell_id=None,
                        target_cell=target_cell,
                    )
                    arc_id = f"source::{start.cabin_id}::{partial_arc.id}"
                    arcs_by_id[arc_id] = DddLayeredTimeArc(
                        id=arc_id,
                        kind=DddLayeredTimeArcKind.SOURCE,
                        source_node_id=None,
                        target_node_id=node.id,
                        cabin_id=start.cabin_id,
                        partial_arc=partial_arc,
                        lower_bound_cost=route_costs[option.id],
                    )

        for layer_index in range(1, max_layer + 1):
            layer_node_ids = tuple(sorted(reachable_by_layer.get(layer_index, ())))
            for node_id in layer_node_ids:
                node = nodes_by_id[node_id]
                if node.cell.upper_seconds > movement.operational_end_seconds:
                    sink_id = f"sink::{node.id}"
                    arcs_by_id[sink_id] = DddLayeredTimeArc(
                        id=sink_id,
                        kind=DddLayeredTimeArcKind.SINK,
                        source_node_id=node.id,
                        target_node_id=None,
                        cabin_id=None,
                        partial_arc=None,
                        lower_bound_cost=problem.objective.terminal_lower_bound(
                            node.cell,
                            tolerance_seconds=self.tolerance_seconds,
                        ),
                    )
                if layer_index >= max_layer:
                    continue
                for option in options_by_state.get(node.state_id, ()):
                    for target_cell in problem.discretization.partition(
                        option.to_state_id
                    ).cells:
                        if not ddd_partial_arc_is_compatible(
                            source_cell=node.cell,
                            fixed_source_time=None,
                            target_cell=target_cell,
                            option=option,
                            operational_end_seconds=movement.operational_end_seconds,
                            tolerance_seconds=self.tolerance_seconds,
                        ):
                            continue
                        target = DddLayeredTimeNode(
                            layer_index + 1,
                            option.to_state_id,
                            target_cell,
                        )
                        add_node(target)
                        partial_arc = DddPartialTimedArc(
                            visit_index=layer_index,
                            route_option_id=option.id,
                            from_state_id=option.from_state_id,
                            to_state_id=option.to_state_id,
                            source_cell_id=node.cell.id,
                            target_cell=target_cell,
                        )
                        arc_id = (
                            f"movement::{node.id}::{partial_arc.id}::"
                            f"{target.id}"
                        )
                        arcs_by_id[arc_id] = DddLayeredTimeArc(
                            id=arc_id,
                            kind=DddLayeredTimeArcKind.MOVEMENT,
                            source_node_id=node.id,
                            target_node_id=target.id,
                            cabin_id=None,
                            partial_arc=partial_arc,
                            lower_bound_cost=route_costs[option.id],
                        )

        result = DddLayeredTimeNetwork(
            nodes=tuple(sorted(nodes_by_id.values(), key=lambda item: item.id)),
            arcs=tuple(sorted(arcs_by_id.values(), key=lambda item: item.id)),
            cabin_ids=tuple(
                sorted(start.cabin_id for start in movement.starts)
            ),
        )
        result.validate()
        return result


class DddAnonymousFlowStatus(StrEnum):
    OPTIMAL = "optimal"
    INFEASIBLE = "infeasible"


@dataclass(frozen=True)
class DddAnonymousFlowValue:
    arc_id: str
    value: int


@dataclass(frozen=True)
class DddAnonymousPrefixFlowValue:
    cabin_id: int
    arc_id: str


@dataclass(frozen=True)
class DddAnonymousFlowResult:
    status: DddAnonymousFlowStatus
    objective_value: float | None
    best_bound: float | None
    arc_values: tuple[DddAnonymousFlowValue, ...]
    prefix_arc_values: tuple[DddAnonymousPrefixFlowValue, ...]
    variable_count: int
    constraint_count: int
    prefix_variable_count: int
    conflict_constraint_count: int
    tracked_prefix_cabin_count: int


@dataclass(frozen=True)
class DddAnonymousFlowMaster:
    output_flag: bool = False
    integrality_tolerance: float = 1e-6

    def solve(
        self,
        network: DddLayeredTimeNetwork,
        *,
        cuts: tuple[DddSupportConflictCut, ...] = (),
    ) -> DddAnonymousFlowResult:
        network.validate()
        if self.integrality_tolerance <= 0:
            raise ValueError("DDD flow integrality tolerance must be positive")
        model = gp.Model("ddd_anonymous_flow")
        model.Params.OutputFlag = int(self.output_flag)
        capacity = len(network.cabin_ids)
        variables = {
            arc.id: model.addVar(
                lb=0.0,
                ub=float(capacity),
                vtype=GRB.INTEGER,
                obj=arc.lower_bound_cost,
                name=f"flow[{index}]",
            )
            for index, arc in enumerate(network.arcs)
        }
        source_arcs_by_cabin: dict[int, list[DddLayeredTimeArc]] = {
            cabin_id: [] for cabin_id in network.cabin_ids
        }
        incoming_by_node: dict[str, list[DddLayeredTimeArc]] = {
            node.id: [] for node in network.nodes
        }
        outgoing_by_node: dict[str, list[DddLayeredTimeArc]] = {
            node.id: [] for node in network.nodes
        }
        for arc in network.arcs:
            if arc.cabin_id is not None:
                source_arcs_by_cabin[arc.cabin_id].append(arc)
            if arc.target_node_id is not None:
                incoming_by_node[arc.target_node_id].append(arc)
            if arc.source_node_id is not None:
                outgoing_by_node[arc.source_node_id].append(arc)
        for cabin_id, arcs in source_arcs_by_cabin.items():
            model.addConstr(
                gp.quicksum(variables[arc.id] for arc in arcs) == 1,
                name=f"source[{cabin_id}]",
            )
        for node_index, node in enumerate(network.nodes):
            model.addConstr(
                gp.quicksum(
                    variables[arc.id] for arc in incoming_by_node[node.id]
                )
                == gp.quicksum(
                    variables[arc.id] for arc in outgoing_by_node[node.id]
                ),
                name=f"flow_conservation[{node_index}]",
            )
        prefix_variables, tracked_prefix_cabin_count = (
            _add_prefix_conflict_formulation(
                model=model,
                network=network,
                flow_variables=variables,
                cuts=cuts,
            )
        )
        model.ModelSense = GRB.MINIMIZE
        model.optimize()
        if model.Status == GRB.INFEASIBLE:
            return DddAnonymousFlowResult(
                status=DddAnonymousFlowStatus.INFEASIBLE,
                objective_value=None,
                best_bound=None,
                arc_values=(),
                prefix_arc_values=(),
                variable_count=model.NumVars,
                constraint_count=model.NumConstrs,
                prefix_variable_count=len(prefix_variables),
                conflict_constraint_count=len(cuts),
                tracked_prefix_cabin_count=tracked_prefix_cabin_count,
            )
        if model.Status != GRB.OPTIMAL:
            raise RuntimeError(f"unexpected DDD flow solver status: {model.Status}")
        values: list[DddAnonymousFlowValue] = []
        for arc in network.arcs:
            raw_value = variables[arc.id].X
            integer_value = round(raw_value)
            if abs(raw_value - integer_value) > self.integrality_tolerance:
                raise RuntimeError("DDD integer flow returned a fractional value")
            if integer_value:
                values.append(DddAnonymousFlowValue(arc.id, integer_value))
        prefix_values: list[DddAnonymousPrefixFlowValue] = []
        for (cabin_id, arc_id), variable in sorted(prefix_variables.items()):
            raw_value = variable.X
            if abs(raw_value - round(raw_value)) > self.integrality_tolerance:
                raise RuntimeError("DDD prefix flow returned a fractional value")
            if round(raw_value):
                prefix_values.append(
                    DddAnonymousPrefixFlowValue(cabin_id, arc_id)
                )
        return DddAnonymousFlowResult(
            status=DddAnonymousFlowStatus.OPTIMAL,
            objective_value=model.ObjVal,
            best_bound=model.ObjBound,
            arc_values=tuple(values),
            prefix_arc_values=tuple(prefix_values),
            variable_count=model.NumVars,
            constraint_count=model.NumConstrs,
            prefix_variable_count=len(prefix_variables),
            conflict_constraint_count=len(cuts),
            tracked_prefix_cabin_count=tracked_prefix_cabin_count,
        )


def _add_prefix_conflict_formulation(
    *,
    model: gp.Model,
    network: DddLayeredTimeNetwork,
    flow_variables: dict[str, gp.Var],
    cuts: tuple[DddSupportConflictCut, ...],
) -> tuple[dict[tuple[int, str], gp.Var], int]:
    if not cuts:
        return {}, 0
    cut_ids: set[str] = set()
    known_route_option_ids = {
        arc.partial_arc.route_option_id
        for arc in network.arcs
        if arc.partial_arc is not None
    }
    max_visit_by_cabin: dict[int, int] = {}
    for cut in cuts:
        cut.validate()
        if cut.id in cut_ids:
            raise ValueError(f"duplicate DDD flow conflict cut id: {cut.id}")
        cut_ids.add(cut.id)
        _validate_prefix_cut_literals(
            cut,
            cabin_ids=set(network.cabin_ids),
            known_route_option_ids=known_route_option_ids,
        )
        for literal in cut.literals:
            max_visit_by_cabin[literal.cabin_id] = max(
                max_visit_by_cabin.get(literal.cabin_id, 0),
                literal.visit_index,
            )

    source_arcs = tuple(
        arc for arc in network.arcs if arc.kind is DddLayeredTimeArcKind.SOURCE
    )
    movement_arcs = tuple(
        arc for arc in network.arcs if arc.kind is DddLayeredTimeArcKind.MOVEMENT
    )
    sink_arcs = tuple(
        arc for arc in network.arcs if arc.kind is DddLayeredTimeArcKind.SINK
    )
    node_by_id = {node.id: node for node in network.nodes}
    incoming_movement_by_node: dict[str, list[DddLayeredTimeArc]] = {
        node.id: [] for node in network.nodes
    }
    outgoing_movement_by_node: dict[str, list[DddLayeredTimeArc]] = {
        node.id: [] for node in network.nodes
    }
    sink_by_node: dict[str, list[DddLayeredTimeArc]] = {
        node.id: [] for node in network.nodes
    }
    for arc in movement_arcs:
        if arc.target_node_id is not None:
            incoming_movement_by_node[arc.target_node_id].append(arc)
        if arc.source_node_id is not None:
            outgoing_movement_by_node[arc.source_node_id].append(arc)
    for arc in sink_arcs:
        if arc.source_node_id is not None:
            sink_by_node[arc.source_node_id].append(arc)

    prefix_variables: dict[tuple[int, str], gp.Var] = {}
    prefix_variables_by_arc_id: dict[str, list[gp.Var]] = {}
    for cabin_id, max_visit_index in sorted(max_visit_by_cabin.items()):
        for arc in movement_arcs:
            partial_arc = arc.partial_arc
            if (
                partial_arc is None
                or partial_arc.visit_index > max_visit_index
            ):
                continue
            variable = model.addVar(
                vtype=GRB.BINARY,
                name=f"prefix_flow[{cabin_id},{len(prefix_variables)}]",
            )
            prefix_variables[(cabin_id, arc.id)] = variable
            prefix_variables_by_arc_id.setdefault(arc.id, []).append(variable)
        for arc in sink_arcs:
            if (
                arc.source_node_id is None
                or node_by_id[arc.source_node_id].layer_index > max_visit_index
            ):
                continue
            variable = model.addVar(
                vtype=GRB.BINARY,
                name=f"prefix_sink[{cabin_id},{len(prefix_variables)}]",
            )
            prefix_variables[(cabin_id, arc.id)] = variable
            prefix_variables_by_arc_id.setdefault(arc.id, []).append(variable)

    for cabin_id, max_visit_index in sorted(max_visit_by_cabin.items()):
        if max_visit_index == 0:
            continue
        for node_index, node in enumerate(network.nodes):
            if node.layer_index > max_visit_index:
                continue
            if node.layer_index == 1:
                incoming = gp.quicksum(
                    flow_variables[arc.id]
                    for arc in source_arcs
                    if arc.cabin_id == cabin_id
                    and arc.target_node_id == node.id
                )
            else:
                incoming = gp.quicksum(
                    prefix_variables[(cabin_id, arc.id)]
                    for arc in incoming_movement_by_node[node.id]
                    if (cabin_id, arc.id) in prefix_variables
                )
            outgoing = gp.quicksum(
                prefix_variables[(cabin_id, arc.id)]
                for arc in (
                    *outgoing_movement_by_node[node.id],
                    *sink_by_node[node.id],
                )
                if (cabin_id, arc.id) in prefix_variables
            )
            model.addConstr(
                incoming == outgoing,
                name=f"prefix_conservation[{cabin_id},{node_index}]",
            )

    for arc_index, arc in enumerate((*movement_arcs, *sink_arcs)):
        tracked = prefix_variables_by_arc_id.get(arc.id, ())
        if tracked:
            model.addConstr(
                gp.quicksum(tracked) <= flow_variables[arc.id],
                name=f"prefix_link[{arc_index}]",
            )

    for cut_index, cut in enumerate(cuts):
        model.addConstr(
            gp.quicksum(
                _prefix_literal_expression(
                    literal=literal,
                    source_arcs=source_arcs,
                    movement_arcs=movement_arcs,
                    flow_variables=flow_variables,
                    prefix_variables=prefix_variables,
                )
                for literal in cut.literals
            )
            <= cut.right_hand_side,
            name=f"prefix_conflict[{cut_index}]",
        )
    return (
        prefix_variables,
        sum(max_visit_index > 0 for max_visit_index in max_visit_by_cabin.values()),
    )


def _validate_prefix_cut_literals(
    cut: DddSupportConflictCut,
    *,
    cabin_ids: set[int],
    known_route_option_ids: set[str],
) -> None:
    by_cabin: dict[int, dict[int, DddSupportLiteral]] = {}
    for literal in cut.literals:
        if literal.cabin_id not in cabin_ids:
            raise ValueError(
                f"DDD flow conflict cut references unknown cabin {literal.cabin_id}"
            )
        if literal.route_option_id not in known_route_option_ids:
            raise ValueError(
                "DDD flow conflict cut references unknown route option "
                f"{literal.route_option_id!r}"
            )
        visits = by_cabin.setdefault(literal.cabin_id, {})
        if literal.visit_index in visits:
            raise ValueError(
                "DDD flow conflict cut has multiple literals for one cabin visit"
            )
        visits[literal.visit_index] = literal
    for cabin_id, visits in by_cabin.items():
        if set(visits) != set(range(max(visits) + 1)):
            raise ValueError(
                f"DDD flow conflict cut cabin {cabin_id} is not a complete prefix"
            )


def _prefix_literal_expression(
    *,
    literal: DddSupportLiteral,
    source_arcs: tuple[DddLayeredTimeArc, ...],
    movement_arcs: tuple[DddLayeredTimeArc, ...],
    flow_variables: dict[str, gp.Var],
    prefix_variables: dict[tuple[int, str], gp.Var],
) -> gp.LinExpr:
    if literal.visit_index == 0:
        return gp.quicksum(
            flow_variables[arc.id]
            for arc in source_arcs
            if arc.cabin_id == literal.cabin_id
            and arc.partial_arc is not None
            and arc.partial_arc.route_option_id == literal.route_option_id
        )
    return gp.quicksum(
        prefix_variables[(literal.cabin_id, arc.id)]
        for arc in movement_arcs
        if arc.partial_arc is not None
        and arc.partial_arc.visit_index == literal.visit_index
        and arc.partial_arc.route_option_id == literal.route_option_id
        and (literal.cabin_id, arc.id) in prefix_variables
    )


@dataclass(frozen=True)
class DddAnonymousFlowDecomposer:
    def decompose(
        self,
        network: DddLayeredTimeNetwork,
        result: DddAnonymousFlowResult,
    ) -> tuple[DddPartialTimedPath, ...]:
        network.validate()
        if result.status is not DddAnonymousFlowStatus.OPTIMAL:
            raise ValueError("only an optimal DDD flow can be decomposed")
        arcs_by_id = network.arcs_by_id
        residual = {item.arc_id: item.value for item in result.arc_values}
        outgoing: dict[str, list[DddLayeredTimeArc]] = {}
        source_by_cabin: dict[int, list[DddLayeredTimeArc]] = {}
        for arc in network.arcs:
            if arc.source_node_id is not None:
                outgoing.setdefault(arc.source_node_id, []).append(arc)
            if arc.cabin_id is not None:
                source_by_cabin.setdefault(arc.cabin_id, []).append(arc)
        for arcs in outgoing.values():
            arcs.sort(key=_decomposition_arc_key)
        for arcs in source_by_cabin.values():
            arcs.sort(key=lambda item: item.id)

        prefix_arc_ids_by_cabin: dict[int, set[str]] = {}
        for item in result.prefix_arc_values:
            if item.arc_id not in arcs_by_id:
                raise RuntimeError("DDD prefix flow references an unknown arc")
            prefix_arc_ids_by_cabin.setdefault(item.cabin_id, set()).add(
                item.arc_id
            )
        remaining_prefix_arcs = {
            cabin_id: set(arc_ids)
            for cabin_id, arc_ids in prefix_arc_ids_by_cabin.items()
        }
        decomposition_order = tuple(
            sorted(
                network.cabin_ids,
                key=lambda cabin_id: (
                    cabin_id not in prefix_arc_ids_by_cabin,
                    cabin_id,
                ),
            )
        )
        paths: list[DddPartialTimedPath] = []
        for cabin_id in decomposition_order:
            prefix_arc_ids = prefix_arc_ids_by_cabin.get(cabin_id, set())
            source_arc = _first_source_for_prefix(
                source_by_cabin.get(cabin_id, ()),
                outgoing=outgoing,
                prefix_arc_ids=prefix_arc_ids,
                residual=residual,
            )
            if source_arc is None or source_arc.partial_arc is None:
                raise RuntimeError(f"DDD flow has no source path for cabin {cabin_id}")
            _consume(source_arc.id, residual)
            partial_arcs = [source_arc.partial_arc]
            node_id = source_arc.target_node_id
            while node_id is not None:
                next_arc = _first_positive_prefix_arc(
                    outgoing.get(node_id, ()),
                    residual=residual,
                    prefix_arc_ids=prefix_arc_ids,
                )
                if next_arc is None:
                    next_arc = _first_positive_arc(
                        outgoing.get(node_id, ()),
                        residual,
                    )
                if next_arc is None:
                    raise RuntimeError("DDD flow path ends before a sink")
                _consume(next_arc.id, residual)
                remaining_prefix_arcs.get(cabin_id, set()).discard(next_arc.id)
                if next_arc.kind is DddLayeredTimeArcKind.SINK:
                    node_id = None
                    continue
                if next_arc.partial_arc is None:
                    raise RuntimeError("DDD movement flow arc has no partial arc")
                partial_arcs.append(next_arc.partial_arc)
                node_id = next_arc.target_node_id
            paths.append(DddPartialTimedPath(cabin_id, tuple(partial_arcs)))
        unconsumed_prefix = {
            cabin_id: tuple(sorted(arc_ids))
            for cabin_id, arc_ids in remaining_prefix_arcs.items()
            if arc_ids
        }
        if unconsumed_prefix:
            raise RuntimeError(
                f"DDD decomposition did not consume prefix flow: {unconsumed_prefix}"
            )
        leftovers = {arc_id: value for arc_id, value in residual.items() if value}
        unknown = set(residual) - set(arcs_by_id)
        if leftovers or unknown:
            raise RuntimeError(f"DDD flow decomposition left residual flow: {leftovers}")
        return tuple(sorted(paths, key=lambda item: item.cabin_id))


@dataclass(frozen=True)
class DddNetworkPathProblemAdapter:
    """Build the resource-free, per-path problem used only for cell lifting.

    Resource usages are deliberately stripped because this adapter checks exact
    event times against selected cells. A successful lift is not a complete
    feasibility certificate; the network refinement solver must subsequently
    validate all lifted paths together against the original movement problem.
    """

    def build(
        self,
        problem: DddNetworkTimeProblem,
        path: DddPartialTimedPath,
    ) -> DddPartialTimeProblem:
        problem.validate()
        starts = tuple(
            start
            for start in problem.movement_problem.starts
            if start.cabin_id == path.cabin_id
        )
        if len(starts) != 1:
            raise ValueError("DDD network path has no unique fixed start")
        terminal_state_id = path.terminal_cell.state_id
        terminal_cost = problem.objective.terminal_cost_by_state_id.get(
            terminal_state_id
        )
        if terminal_cost is None:
            terminal_cost = DddTerminalThresholdCost(
                state_id=terminal_state_id,
                threshold_seconds=0.0,
                before_cost=problem.objective.default_terminal_cost,
                at_or_after_cost=problem.objective.default_terminal_cost,
            )
        movement = replace(
            problem.movement_problem,
            starts=starts,
            route_options=tuple(
                replace(option, resource_usages=())
                for option in problem.movement_problem.route_options
            ),
            resources=(),
        )
        result = DddPartialTimeProblem(
            movement_problem=movement,
            terminal_state_id=terminal_state_id,
            discretization=problem.discretization,
            objective=DddTimeSpaceObjective(
                route_option_costs=problem.objective.route_option_costs,
                terminal_cost=terminal_cost,
            ),
        )
        result.validate()
        return result


def _first_positive_arc(
    arcs: tuple[DddLayeredTimeArc, ...] | list[DddLayeredTimeArc],
    residual: dict[str, int],
) -> DddLayeredTimeArc | None:
    return next((arc for arc in arcs if residual.get(arc.id, 0) > 0), None)


def _first_positive_prefix_arc(
    arcs: tuple[DddLayeredTimeArc, ...] | list[DddLayeredTimeArc],
    *,
    residual: dict[str, int],
    prefix_arc_ids: set[str],
) -> DddLayeredTimeArc | None:
    return next(
        (
            arc
            for arc in arcs
            if arc.id in prefix_arc_ids and residual.get(arc.id, 0) > 0
        ),
        None,
    )


def _first_source_for_prefix(
    arcs: tuple[DddLayeredTimeArc, ...] | list[DddLayeredTimeArc],
    *,
    outgoing: dict[str, list[DddLayeredTimeArc]],
    prefix_arc_ids: set[str],
    residual: dict[str, int],
) -> DddLayeredTimeArc | None:
    if prefix_arc_ids:
        matching = next(
            (
                arc
                for arc in arcs
                if residual.get(arc.id, 0) > 0
                and arc.target_node_id is not None
                and any(
                    outgoing_arc.id in prefix_arc_ids
                    for outgoing_arc in outgoing.get(arc.target_node_id, ())
                )
            ),
            None,
        )
        if matching is not None:
            return matching
    return _first_positive_arc(arcs, residual)


def _decomposition_arc_key(arc: DddLayeredTimeArc) -> tuple[object, ...]:
    if arc.partial_arc is None:
        return (1, math.inf, math.inf, arc.id)
    return (
        0,
        arc.partial_arc.target_cell.lower_seconds,
        arc.partial_arc.target_cell.upper_seconds,
        arc.partial_arc.route_option_id,
        arc.id,
    )


def _consume(arc_id: str, residual: dict[str, int]) -> None:
    value = residual.get(arc_id, 0)
    if value <= 0:
        raise RuntimeError(f"DDD flow arc {arc_id!r} has no residual value")
    residual[arc_id] = value - 1
