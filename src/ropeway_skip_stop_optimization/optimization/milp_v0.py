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
    MilpV0VariableStrategy,
)
from ropeway_skip_stop_optimization.optimization.movement_plan_validation import (
    validate_optimized_movement_plan,
)
from ropeway_skip_stop_optimization.optimization.variable_index import (
    build_dense_milp_v0_variable_index,
    build_sparse_reachability_milp_v0_variable_index,
)
from ropeway_skip_stop_optimization.progress import ProgressReporter


def solve_milp_v0(
    discrete_scenario: DiscreteScenario,
    config: MilpV0Config,
    *,
    progress: ProgressReporter | None = None,
) -> MilpMovementPlanResult:
    progress = progress or ProgressReporter()
    try:
        import gurobipy as gp
        from gurobipy import GRB
    except ImportError as error:
        raise RuntimeError("gurobipy is required for MILP optimization") from error

    config.validate()
    if config.horizon_steps > discrete_scenario.horizon_steps:
        raise ValueError("MILP v0 horizon_steps exceeds discrete scenario horizon")

    with progress.phase("milp_v0.build_graph_index"):
        index = build_discrete_graph_index(discrete_scenario)
    with progress.phase("milp_v0.allowed_arcs"):
        allowed_arc_ids = _allowed_arc_ids(discrete_scenario, config)
    active_cabin_ids = tuple(start.cabin_id for start in config.fixed_starts)
    fixed_start_by_cabin = {start.cabin_id: start.node_id for start in config.fixed_starts}
    missing_start_nodes = set(fixed_start_by_cabin.values()) - index.nodes_by_id.keys()
    if missing_start_nodes:
        raise ValueError(f"MILP v0 fixed starts reference unknown nodes: {missing_start_nodes}")
    if config.variable_strategy is MilpV0VariableStrategy.DENSE:
        with progress.phase("milp_v0.build_dense_variable_index"):
            variable_index = build_dense_milp_v0_variable_index(
                index,
                config.fixed_starts,
                allowed_arc_ids,
                config.horizon_steps,
            )
    elif config.variable_strategy is MilpV0VariableStrategy.SPARSE_REACHABILITY:
        with progress.phase("milp_v0.build_sparse_variable_index"):
            variable_index = build_sparse_reachability_milp_v0_variable_index(
                index,
                config.fixed_starts,
                allowed_arc_ids,
                config.horizon_steps,
                progress=progress,
            )
    else:
        raise NotImplementedError(f"MILP v0 variable strategy {config.variable_strategy.value!r} is not implemented")

    with progress.phase(
        f"milp_v0.create_variables x={len(variable_index.x_keys)} y={len(variable_index.y_keys)}"
    ):
        model = gp.Model("ropeway_milp_v0")
        x = model.addVars(variable_index.x_keys, vtype=GRB.BINARY, name="x")
        y = model.addVars(variable_index.y_keys, vtype=GRB.BINARY, name="y")

    with progress.phase("milp_v0.add_position_constraints"):
        for cabin_id in progress.iter(active_cabin_ids, label="position constraints", total=len(active_cabin_ids)):
            for time_step in range(config.horizon_steps + 1):
                model.addConstr(
                    gp.quicksum(
                        x[cabin_id, time_step, node_id]
                        for node_id in variable_index.node_ids_by_cabin_time[cabin_id, time_step]
                    )
                    == 1,
                    name=f"position_once[{cabin_id},{time_step}]",
                )

    with progress.phase("milp_v0.add_flow_constraints"):
        outgoing_terms = variable_index.out_arc_ids_by_cabin_time_node.items()
        for (cabin_id, time_step, node_id), out_arc_ids in progress.iter(
            outgoing_terms,
            label="outgoing flow constraints",
            total=len(variable_index.out_arc_ids_by_cabin_time_node),
        ):
            model.addConstr(
                gp.quicksum(y[cabin_id, time_step, arc_id] for arc_id in out_arc_ids)
                == x[cabin_id, time_step, node_id],
                name=f"outgoing[{cabin_id},{time_step},{node_id}]",
            )

        incoming_terms = variable_index.in_arc_ids_by_cabin_time_node.items()
        for (cabin_id, time_step, node_id), in_arc_ids in progress.iter(
            incoming_terms,
            label="incoming flow constraints",
            total=len(variable_index.in_arc_ids_by_cabin_time_node),
        ):
            model.addConstr(
                gp.quicksum(y[cabin_id, time_step - 1, arc_id] for arc_id in in_arc_ids)
                == x[cabin_id, time_step, node_id],
                name=f"incoming[{cabin_id},{time_step},{node_id}]",
            )

    with progress.phase("milp_v0.add_initial_constraints"):
        for cabin_id, node_id in fixed_start_by_cabin.items():
            model.addConstr(x[cabin_id, 0, node_id] == 1, name=f"initial[{cabin_id}]")

    with progress.phase("milp_v0.add_conflict_constraints"):
        hard_node_constraints = tuple(
            constraint
            for constraint in discrete_scenario.constraints
            if constraint.strength is DiscreteConstraintStrength.HARD and constraint.node_ids
        )
        for time_step in range(config.horizon_steps + 1):
            for node_id in index.nodes_by_id:
                participant_cabin_ids = variable_index.reachable_cabin_ids_by_time_node.get((time_step, node_id), ())
                if len(participant_cabin_ids) < 2:
                    continue
                participants = [x[cabin_id, time_step, node_id] for cabin_id in participant_cabin_ids]
                if len(participants) < 2:
                    continue
                model.addConstr(
                    gp.quicksum(participants) <= 1,
                    name=f"node_occupancy[{time_step},{node_id}]",
                )
            for constraint in hard_node_constraints:
                participants = [
                    x[cabin_id, time_step, node_id]
                    for node_id in constraint.node_ids
                    for cabin_id in variable_index.reachable_cabin_ids_by_time_node.get((time_step, node_id), ())
                ]
                if len(participants) < 2:
                    continue
                model.addConstr(
                    gp.quicksum(participants) <= 1,
                    name=f"conflict[{constraint.kind.value},{constraint.scope.value},{constraint.id},{time_step}]",
                )

    with progress.phase("milp_v0.optimize"):
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
    with progress.phase("milp_v0.extract_solution"):
        for cabin_id in progress.iter(active_cabin_ids, label="extract solution", total=len(active_cabin_ids)):
            selected_node_id_by_time = _selected_nodes_by_time(
                model,
                x,
                variable_index.node_ids_by_cabin_time,
                cabin_id,
                config.horizon_steps,
            )
            selected_arc_id_by_time = _selected_arcs_by_time(
                model,
                y,
                variable_index.arc_ids_by_cabin_time,
                cabin_id,
                config.horizon_steps,
            )
            positions: list[CabinPosition] = []
            selected_arc_ids: list[str] = []
            for time_step in range(config.horizon_steps + 1):
                incoming_arc_id = None
                if time_step > 0:
                    incoming_arc_id = selected_arc_ids[-1]
                positions.append(
                    CabinPosition(
                        time_step=time_step,
                        node_id=selected_node_id_by_time[time_step],
                        incoming_arc_id=incoming_arc_id,
                    )
                )
                if time_step < config.horizon_steps:
                    selected_arc_ids.append(selected_arc_id_by_time[time_step])
            selected_arc_ids_by_cabin[cabin_id] = tuple(selected_arc_ids)
            trajectories.append(CabinTrajectory(cabin_id=cabin_id, positions=tuple(positions)))

    movement_plan = MovementPlan(
        discrete_scenario_id=discrete_scenario.id,
        horizon_steps=config.horizon_steps,
        trajectories=tuple(trajectories),
    )
    with progress.phase("milp_v0.validate_solution"):
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


def _selected_nodes_by_time(
    model,
    x,
    node_ids_by_cabin_time: dict[tuple[int, int], tuple[str, ...]],
    cabin_id: int,
    horizon_steps: int,
) -> dict[int, str]:
    keys = [
        (cabin_id, time_step, node_id)
        for time_step in range(horizon_steps + 1)
        for node_id in node_ids_by_cabin_time[cabin_id, time_step]
    ]
    values = model.getAttr("X", [x[key] for key in keys])
    selected: dict[int, list[str]] = {}
    for (_, time_step, node_id), value in zip(keys, values, strict=True):
        if value > 0.5:
            selected.setdefault(time_step, []).append(node_id)
    return {
        time_step: _selected_id(selected.get(time_step, ()))
        for time_step in range(horizon_steps + 1)
    }


def _selected_arcs_by_time(
    model,
    y,
    arc_ids_by_cabin_time: dict[tuple[int, int], tuple[str, ...]],
    cabin_id: int,
    horizon_steps: int,
) -> dict[int, str]:
    keys = [
        (cabin_id, time_step, arc_id)
        for time_step in range(horizon_steps)
        for arc_id in arc_ids_by_cabin_time[cabin_id, time_step]
    ]
    values = model.getAttr("X", [y[key] for key in keys])
    selected: dict[int, list[str]] = {}
    for (_, time_step, arc_id), value in zip(keys, values, strict=True):
        if value > 0.5:
            selected.setdefault(time_step, []).append(arc_id)
    return {
        time_step: _selected_id(selected.get(time_step, ()))
        for time_step in range(horizon_steps)
    }


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
