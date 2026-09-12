from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import gurobipy as gp
from gurobipy import GRB

from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_preparation import (
    DddPreparedArcFlowProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceResourceOccurrence,
    DddReferenceSolution,
    DddReferenceTrajectory,
    build_ddd_reference_visit,
    validate_ddd_reference_solution,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_seconds_to_tick,
    ddd_tick_to_seconds,
)


@dataclass(slots=True)
class DddArcFlowMovementMaster:
    """One complete Movement master with stable arc-indexed variables."""

    prepared: DddPreparedArcFlowProblem
    model: gp.Model
    route_by_arc_id: dict[str, gp.Var]
    movement_constraint_count: int
    resource_row_count: int

    @property
    def movement_variable_count(self) -> int:
        return len(self.route_by_arc_id)

    def apply_seed(
        self,
        trajectories: tuple[DddReferenceTrajectory, ...],
    ) -> None:
        if not trajectories:
            return
        values = build_ddd_arc_flow_movement_values(
            self.prepared,
            DddReferenceSolution(trajectories),
        )
        for arc_id, variable in self.route_by_arc_id.items():
            variable.Start = values[arc_id]

    def extract_solution(
        self,
        *,
        boundary_occurrences: tuple[DddReferenceResourceOccurrence, ...] = (),
        values: dict[str, float] | None = None,
    ) -> DddReferenceSolution:
        movement = self.prepared.movement
        options = {option.id: option for option in movement.route_options}
        boundary_by_cabin: dict[int, list[DddReferenceResourceOccurrence]] = (
            defaultdict(list)
        )
        for occurrence in boundary_occurrences:
            boundary_by_cabin[occurrence.cabin_id].append(occurrence)
        trajectories: list[DddReferenceTrajectory] = []
        for network in self.prepared.networks:
            visits = []
            for arc in network.arcs:
                if (
                    (self.route_by_arc_id[arc.id].X if values is None else values[arc.id]) <= 0.5
                    or not arc.source_active
                    or arc.option_id is None
                ):
                    continue
                visits.append(
                    build_ddd_reference_visit(
                        start=network.start,
                        visit_index=arc.visit_index,
                        switch_time_seconds=ddd_tick_to_seconds(arc.source_tick),
                        option=options[arc.option_id],
                        operational_end_seconds=movement.operational_end_seconds,
                        tolerance_seconds=0.0,
                        wait_seconds=ddd_tick_to_seconds(arc.wait_tick),
                    )
                )
            trajectories.append(
                DddReferenceTrajectory(
                    cabin_id=network.cabin_id,
                    visits=tuple(sorted(visits, key=lambda item: item.visit_index)),
                    boundary_resource_occurrences=tuple(
                        sorted(
                            boundary_by_cabin.get(network.cabin_id, ()),
                            key=lambda item: (
                                item.resource_id,
                                item.follower_enter_time_seconds,
                                item.visit_index,
                            ),
                        )
                    ),
                )
            )
        return DddReferenceSolution(tuple(trajectories))


@dataclass(frozen=True, slots=True)
class DddArcFlowMovementMasterBuilder:
    """Build only the exact cabin flow and physical resource rows."""

    def build(
        self,
        *,
        model: gp.Model,
        prepared: DddPreparedArcFlowProblem,
        variable_type: str = GRB.BINARY,
        add_eager_resource_rows: bool = True,
    ) -> DddArcFlowMovementMaster:
        prepared.validate()
        if (
            add_eager_resource_rows
            and not prepared.labeled_resource_cliques_complete
        ):
            raise ValueError(
                "labeled Movement master requires complete labeled resource cliques"
            )
        if variable_type not in {GRB.BINARY, GRB.CONTINUOUS}:
            raise ValueError("Movement master variable type is invalid")
        route = {
            arc.id: model.addVar(
                lb=0.0,
                ub=1.0,
                vtype=variable_type,
                name=f"route[{index}]",
            )
            for index, arc in enumerate(prepared.arcs)
        }
        movement_constraints = self._add_movement_flow(
            model,
            prepared,
            route,
        )
        resource_rows = (
            self._add_resource_rows(model, prepared, route)
            if add_eager_resource_rows
            else 0
        )
        return DddArcFlowMovementMaster(
            prepared=prepared,
            model=model,
            route_by_arc_id=route,
            movement_constraint_count=movement_constraints,
            resource_row_count=resource_rows,
        )

    @staticmethod
    def _add_movement_flow(
        model: gp.Model,
        prepared: DddPreparedArcFlowProblem,
        route: dict[str, gp.Var],
    ) -> int:
        constraint_count = 0
        for network in prepared.networks:
            outgoing: dict[tuple[int, int, bool], list[gp.Var]] = defaultdict(list)
            incoming: dict[tuple[int, int, bool], list[gp.Var]] = defaultdict(list)
            for arc in network.arcs:
                outgoing[arc.source_node].append(route[arc.id])
                incoming[arc.target_node].append(route[arc.id])
            source = (0, network.start.time_tick, True)
            model.addConstr(
                gp.quicksum(outgoing[source]) == 1,
                name=f"source[{network.cabin_id}]",
            )
            constraint_count += 1
            for node in network.nodes:
                if node == source or node[0] == network.start.max_visit_count:
                    continue
                model.addConstr(
                    gp.quicksum(incoming[node]) == gp.quicksum(outgoing[node]),
                    name=(
                        f"flow[{network.cabin_id},{node[0]},{node[1]},"
                        f"{int(node[2])}]"
                    ),
                )
                constraint_count += 1
            model.addConstr(
                gp.quicksum(
                    variable
                    for node in network.nodes
                    if node[0] == network.start.max_visit_count and not node[2]
                    for variable in incoming[node]
                )
                == 1,
                name=f"sink[{network.cabin_id}]",
            )
            constraint_count += 1
        return constraint_count

    @staticmethod
    def _add_resource_rows(
        model: gp.Model,
        prepared: DddPreparedArcFlowProblem,
        route: dict[str, gp.Var],
    ) -> int:
        count = 0
        for clique in prepared.resource_cliques:
            if len(clique.coefficients) == 1 and clique.coefficients[0][1] == 1:
                continue
            model.addConstr(
                gp.quicksum(
                    coefficient * route[arc_id]
                    for arc_id, coefficient in clique.coefficients
                )
                <= 1,
                name=f"resource[{count}]",
            )
            count += 1
        return count


def build_ddd_arc_flow_movement_values(
    prepared: DddPreparedArcFlowProblem,
    solution: DddReferenceSolution,
) -> dict[str, float]:
    """Project one complete reference solution onto every Movement arc."""

    prepared.validate()
    validate_ddd_reference_solution(
        prepared.movement,
        solution,
        waiting_policy=prepared.problem.resolved_trajectory_problem.waiting_policy,
    )
    trajectory_by_cabin = {
        trajectory.cabin_id: trajectory for trajectory in solution.trajectories
    }
    selected: set[str] = set()
    for network in prepared.networks:
        trajectory = trajectory_by_cabin[network.cabin_id]
        visit_by_index = {
            visit.visit_index: visit for visit in trajectory.visits
        }
        node = (0, network.start.time_tick, True)
        for visit_index in range(network.start.max_visit_count):
            candidates = tuple(
                arc for arc in network.arcs if arc.source_node == node
            )
            if not candidates:
                raise ValueError("reference solution leaves the Movement DAG")
            if node[2]:
                visit = visit_by_index.get(visit_index)
                if visit is None:
                    raise ValueError("reference solution misses an active Movement visit")
                matching = tuple(
                    arc
                    for arc in candidates
                    if arc.option_id == visit.route_option_id
                    and arc.source_tick
                    == ddd_seconds_to_tick(visit.switch_time_seconds)
                    and arc.wait_tick == ddd_seconds_to_tick(visit.wait_seconds)
                )
            else:
                matching = tuple(arc for arc in candidates if arc.option_id is None)
            if len(matching) != 1:
                raise ValueError("reference solution does not select one Movement arc")
            arc = matching[0]
            selected.add(arc.id)
            node = arc.target_node
    return {
        arc.id: 1.0 if arc.id in selected else 0.0
        for arc in prepared.arcs
    }
