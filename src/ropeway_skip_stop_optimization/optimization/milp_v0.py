from __future__ import annotations

from ropeway_skip_stop_optimization.models import (
    CabinPosition,
    CabinTrajectory,
    DiscreteArcKind,
    DiscreteScenario,
    DiscreteConstraintStrength,
    MovementPlan,
)
from ropeway_skip_stop_optimization.optimization.graph_index import build_discrete_graph_index
from ropeway_skip_stop_optimization.optimization.models import (
    MilpMovementPlanResult,
    MilpSolveMetadata,
    MilpV0Config,
)
from ropeway_skip_stop_optimization.optimization.movement_plan_validation import (
    validate_optimized_movement_plan,
)


def solve_milp_v0(
    discrete_scenario: DiscreteScenario,
    config: MilpV0Config,
) -> MilpMovementPlanResult:
    try:
        import gurobipy as gp
        from gurobipy import GRB
    except ImportError as error:
        raise RuntimeError("gurobipy is required for MILP optimization") from error

    config.validate()
    if config.horizon_steps > discrete_scenario.horizon_steps:
        raise ValueError("MILP v0 horizon_steps exceeds discrete scenario horizon")

    index = build_discrete_graph_index(discrete_scenario)
    allowed_arc_ids = _allowed_arc_ids(discrete_scenario, config)
    active_cabin_ids = tuple(start.cabin_id for start in config.fixed_starts)
    fixed_start_by_cabin = {start.cabin_id: start.node_id for start in config.fixed_starts}
    missing_start_nodes = set(fixed_start_by_cabin.values()) - index.nodes_by_id.keys()
    if missing_start_nodes:
        raise ValueError(f"MILP v0 fixed starts reference unknown nodes: {missing_start_nodes}")

    model = gp.Model("ropeway_milp_v0")
    x = model.addVars(
        active_cabin_ids,
        range(config.horizon_steps + 1),
        tuple(index.nodes_by_id),
        vtype=GRB.BINARY,
        name="x",
    )
    y = model.addVars(
        active_cabin_ids,
        range(config.horizon_steps),
        allowed_arc_ids,
        vtype=GRB.BINARY,
        name="y",
    )

    for cabin_id in active_cabin_ids:
        for time_step in range(config.horizon_steps + 1):
            model.addConstr(
                gp.quicksum(x[cabin_id, time_step, node_id] for node_id in index.nodes_by_id) == 1,
                name=f"position_once[{cabin_id},{time_step}]",
            )

    allowed_arc_id_set = set(allowed_arc_ids)
    for cabin_id in active_cabin_ids:
        for time_step in range(config.horizon_steps):
            for node_id in index.nodes_by_id:
                out_arc_ids = tuple(
                    arc_id
                    for arc_id in index.out_arc_ids_by_node_id[node_id]
                    if arc_id in allowed_arc_id_set
                )
                model.addConstr(
                    gp.quicksum(y[cabin_id, time_step, arc_id] for arc_id in out_arc_ids)
                    == x[cabin_id, time_step, node_id],
                    name=f"outgoing[{cabin_id},{time_step},{node_id}]",
                )
                in_arc_ids = tuple(
                    arc_id
                    for arc_id in index.in_arc_ids_by_node_id[node_id]
                    if arc_id in allowed_arc_id_set
                )
                model.addConstr(
                    gp.quicksum(y[cabin_id, time_step, arc_id] for arc_id in in_arc_ids)
                    == x[cabin_id, time_step + 1, node_id],
                    name=f"incoming[{cabin_id},{time_step},{node_id}]",
                )

    for cabin_id, node_id in fixed_start_by_cabin.items():
        model.addConstr(x[cabin_id, 0, node_id] == 1, name=f"initial[{cabin_id}]")

    for time_step in range(config.horizon_steps + 1):
        for node_id in index.nodes_by_id:
            model.addConstr(
                gp.quicksum(x[cabin_id, time_step, node_id] for cabin_id in active_cabin_ids) <= 1,
                name=f"node_occupancy[{time_step},{node_id}]",
            )
        for constraint in discrete_scenario.constraints:
            if constraint.strength is not DiscreteConstraintStrength.HARD:
                continue
            if not constraint.node_ids:
                continue
            model.addConstr(
                gp.quicksum(
                    x[cabin_id, time_step, node_id]
                    for cabin_id in active_cabin_ids
                    for node_id in constraint.node_ids
                )
                <= 1,
                name=f"conflict[{constraint.kind.value},{constraint.scope.value},{constraint.id},{time_step}]",
            )

    model.setObjective(0.0, GRB.MINIMIZE)
    model.optimize()

    status = _status_name(GRB, model.Status)
    objective_value = model.ObjVal if model.SolCount > 0 else None
    if model.SolCount == 0:
        return MilpMovementPlanResult(
            movement_plan=None,
            metadata=MilpSolveMetadata(
                status=status,
                objective_value=objective_value,
                selected_arc_ids_by_cabin={},
                variable_count=model.NumVars,
                constraint_count=model.NumConstrs,
            ),
        )

    selected_arc_ids_by_cabin: dict[int, tuple[str, ...]] = {}
    trajectories: list[CabinTrajectory] = []
    for cabin_id in active_cabin_ids:
        positions: list[CabinPosition] = []
        selected_arc_ids: list[str] = []
        for time_step in range(config.horizon_steps + 1):
            selected_node_id = _selected_id(
                node_id
                for node_id in index.nodes_by_id
                if x[cabin_id, time_step, node_id].X > 0.5
            )
            incoming_arc_id = None
            if time_step > 0:
                incoming_arc_id = selected_arc_ids[-1]
            positions.append(
                CabinPosition(
                    time_step=time_step,
                    node_id=selected_node_id,
                    incoming_arc_id=incoming_arc_id,
                )
            )
            if time_step < config.horizon_steps:
                selected_arc_ids.append(
                    _selected_id(
                        arc_id
                        for arc_id in allowed_arc_ids
                        if y[cabin_id, time_step, arc_id].X > 0.5
                    )
                )
        selected_arc_ids_by_cabin[cabin_id] = tuple(selected_arc_ids)
        trajectories.append(CabinTrajectory(cabin_id=cabin_id, positions=tuple(positions)))

    movement_plan = MovementPlan(
        discrete_scenario_id=discrete_scenario.id,
        horizon_steps=config.horizon_steps,
        trajectories=tuple(trajectories),
    )
    validation = validate_optimized_movement_plan(
        discrete_scenario,
        movement_plan,
        fixed_starts=config.fixed_starts,
        selected_arc_ids_by_cabin=selected_arc_ids_by_cabin,
    )
    validation.raise_for_errors()

    return MilpMovementPlanResult(
        movement_plan=movement_plan,
        metadata=MilpSolveMetadata(
            status=status,
            objective_value=objective_value,
            selected_arc_ids_by_cabin=selected_arc_ids_by_cabin,
            variable_count=model.NumVars,
            constraint_count=model.NumConstrs,
        ),
    )


def _allowed_arc_ids(discrete_scenario: DiscreteScenario, config: MilpV0Config) -> tuple[str, ...]:
    allowed_arc_ids: list[str] = []
    for arc in discrete_scenario.arcs:
        if arc.kind is DiscreteArcKind.WAIT and not config.allow_wait_arcs:
            continue
        if arc.kind is DiscreteArcKind.MOVE and not config.allow_move_arcs:
            continue
        if not config.allow_skip_arcs and arc.source_route_id and "skip" in arc.source_route_id.lower():
            continue
        allowed_arc_ids.append(arc.id)
    if not allowed_arc_ids:
        raise ValueError("MILP v0 has no allowed arcs")
    return tuple(allowed_arc_ids)


def _selected_id(ids) -> str:
    selected = tuple(ids)
    if len(selected) != 1:
        raise ValueError(f"expected exactly one selected id, got {selected!r}")
    return selected[0]


def _status_name(grb, status: int) -> str:
    status_names = {
        grb.LOADED: "loaded",
        grb.OPTIMAL: "optimal",
        grb.INFEASIBLE: "infeasible",
        grb.INF_OR_UNBD: "infeasible_or_unbounded",
        grb.UNBOUNDED: "unbounded",
        grb.CUTOFF: "cutoff",
        grb.ITERATION_LIMIT: "iteration_limit",
        grb.NODE_LIMIT: "node_limit",
        grb.TIME_LIMIT: "time_limit",
        grb.SOLUTION_LIMIT: "solution_limit",
        grb.INTERRUPTED: "interrupted",
        grb.NUMERIC: "numeric",
        grb.SUBOPTIMAL: "suboptimal",
    }
    return status_names.get(status, f"status_{status}")
