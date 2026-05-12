from __future__ import annotations

from ropeway_skip_stop_optimization.models import (
    DiscreteArcKind,
    DiscreteScenario,
)
from ropeway_skip_stop_optimization.optimization.discrete_time.graph_index import build_discrete_graph_index
from ropeway_skip_stop_optimization.optimization.discrete_time.movement_model_builder import (
    add_conflict_constraints,
    add_flow_constraints,
    add_initial_constraints,
    add_position_constraints,
    create_movement_variables,
    extract_movement_plan,
)
from ropeway_skip_stop_optimization.optimization.discrete_time.models import (
    MilpMovementPlanResult,
    MilpSolveMetadata,
    MilpV0Config,
    MilpV0VariableStrategy,
)
from ropeway_skip_stop_optimization.optimization.discrete_time.validation import (
    validate_optimized_movement_plan,
)
from ropeway_skip_stop_optimization.optimization.discrete_time.variable_index import (
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
        x, y = create_movement_variables(model, GRB, variable_index)

    with progress.phase("milp_v0.add_position_constraints"):
        add_position_constraints(
            model,
            gp,
            x,
            variable_index,
            active_cabin_ids,
            config.horizon_steps,
            progress=progress,
        )

    with progress.phase("milp_v0.add_flow_constraints"):
        add_flow_constraints(model, gp, x, y, variable_index, progress=progress)

    with progress.phase("milp_v0.add_initial_constraints"):
        add_initial_constraints(model, x, fixed_start_by_cabin)

    with progress.phase("milp_v0.add_conflict_constraints"):
        add_conflict_constraints(
            model,
            gp,
            x,
            discrete_scenario,
            index,
            variable_index,
            config.horizon_steps,
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

    with progress.phase("milp_v0.extract_solution"):
        movement_plan, selected_arc_ids_by_cabin = extract_movement_plan(
            model,
            x,
            y,
            variable_index,
            discrete_scenario.id,
            active_cabin_ids,
            config.horizon_steps,
            progress=progress,
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
