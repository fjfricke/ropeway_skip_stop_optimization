from __future__ import annotations

from ropeway_skip_stop_optimization.models import DiscreteScenario
from ropeway_skip_stop_optimization.optimization.graph_index import build_discrete_graph_index
from ropeway_skip_stop_optimization.optimization.milp_v0 import _allowed_arc_ids, _status_name
from ropeway_skip_stop_optimization.optimization.movement_milp_builder import (
    add_conflict_constraints,
    add_flow_constraints,
    add_initial_constraints,
    add_position_constraints,
    create_movement_variables,
    extract_movement_plan,
)
from ropeway_skip_stop_optimization.optimization.models import (
    MilpPassengerWaitingMetadata,
    MilpPassengerWaitingResult,
    MilpV0Config,
    MilpV0VariableStrategy,
    MilpV1PassengerWaitingObjective,
    MilpV1PassengerWaitingConfig,
)
from ropeway_skip_stop_optimization.optimization.movement_plan_validation import (
    validate_optimized_movement_plan,
)
from ropeway_skip_stop_optimization.optimization.passenger_index import build_passenger_milp_index
from ropeway_skip_stop_optimization.optimization.variable_index import (
    build_dense_milp_v0_variable_index,
    build_sparse_reachability_milp_v0_variable_index,
)
from ropeway_skip_stop_optimization.progress import ProgressReporter


def solve_milp_v1_passenger_waiting(
    discrete_scenario: DiscreteScenario,
    config: MilpV1PassengerWaitingConfig,
    *,
    progress: ProgressReporter | None = None,
) -> MilpPassengerWaitingResult:
    progress = progress or ProgressReporter()
    try:
        import gurobipy as gp
        from gurobipy import GRB
    except ImportError as error:
        raise RuntimeError("gurobipy is required for MILP optimization") from error

    config.validate()
    if config.horizon_steps > discrete_scenario.horizon_steps:
        raise ValueError("MILP v1 passenger waiting horizon_steps exceeds discrete scenario horizon")

    with progress.phase("milp_v1.build_graph_index"):
        graph_index = build_discrete_graph_index(discrete_scenario)
    with progress.phase("milp_v1.allowed_arcs"):
        movement_config = _movement_config(config)
        allowed_arc_ids = _allowed_arc_ids(discrete_scenario, movement_config)

    active_cabin_ids = tuple(start.cabin_id for start in config.fixed_starts)
    fixed_start_by_cabin = {start.cabin_id: start.node_id for start in config.fixed_starts}
    missing_start_nodes = set(fixed_start_by_cabin.values()) - graph_index.nodes_by_id.keys()
    if missing_start_nodes:
        raise ValueError(f"MILP v1 fixed starts reference unknown nodes: {missing_start_nodes}")

    if config.variable_strategy is MilpV0VariableStrategy.DENSE:
        with progress.phase("milp_v1.build_dense_variable_index"):
            variable_index = build_dense_milp_v0_variable_index(
                graph_index,
                config.fixed_starts,
                allowed_arc_ids,
                config.horizon_steps,
            )
    elif config.variable_strategy is MilpV0VariableStrategy.SPARSE_REACHABILITY:
        with progress.phase("milp_v1.build_sparse_variable_index"):
            variable_index = build_sparse_reachability_milp_v0_variable_index(
                graph_index,
                config.fixed_starts,
                allowed_arc_ids,
                config.horizon_steps,
                progress=progress,
            )
    else:
        raise NotImplementedError(f"MILP v1 variable strategy {config.variable_strategy.value!r} is not implemented")

    with progress.phase("milp_v1.build_passenger_index"):
        passenger_index = build_passenger_milp_index(
            discrete_scenario,
            graph_index,
            variable_index,
            config.fixed_starts,
            allowed_arc_ids,
            config.horizon_steps,
        )

    destinations = tuple(sorted({destination for _, destination in passenger_index.od_pairs}))
    q_keys = tuple(
        (time_step, origin, destination)
        for time_step in range(config.horizon_steps + 1)
        for origin, destination in passenger_index.od_pairs
    )
    b_keys = tuple(passenger_index.boarding_candidates_by_cabin_time_od)
    z_keys = tuple(
        (cabin_id, time_step, destination)
        for cabin_id in active_cabin_ids
        for time_step in range(config.horizon_steps + 1)
        for destination in destinations
    )
    e_keys = tuple(passenger_index.alighting_candidates_by_cabin_time_destination)

    with progress.phase(
        "milp_v1.create_variables "
        f"x={len(variable_index.x_keys)} y={len(variable_index.y_keys)} "
        f"q={len(q_keys)} b={len(b_keys)} z={len(z_keys)} e={len(e_keys)}"
    ):
        model = gp.Model("ropeway_milp_v1_passenger_waiting")
        x, y = create_movement_variables(model, GRB, variable_index)
        q = model.addVars(q_keys, vtype=GRB.INTEGER, lb=0, name="q")
        b = model.addVars(b_keys, vtype=GRB.INTEGER, lb=0, name="b")
        z = model.addVars(z_keys, vtype=GRB.INTEGER, lb=0, name="z")
        e = model.addVars(e_keys, vtype=GRB.INTEGER, lb=0, name="e")

    with progress.phase("milp_v1.add_movement_position_constraints"):
        add_position_constraints(
            model,
            gp,
            x,
            variable_index,
            active_cabin_ids,
            config.horizon_steps,
            progress=progress,
        )
    with progress.phase("milp_v1.add_movement_flow_constraints"):
        add_flow_constraints(model, gp, x, y, variable_index, progress=progress)
    with progress.phase("milp_v1.add_movement_initial_constraints"):
        add_initial_constraints(model, x, fixed_start_by_cabin)
    with progress.phase("milp_v1.add_movement_conflict_constraints"):
        add_conflict_constraints(
            model,
            gp,
            x,
            discrete_scenario,
            graph_index,
            variable_index,
            config.horizon_steps,
        )

    with progress.phase("milp_v1.add_passenger_queue_constraints"):
        _add_queue_constraints(model, gp, q, b, passenger_index, active_cabin_ids, config.horizon_steps)
    with progress.phase("milp_v1.add_passenger_boarding_constraints"):
        _add_boarding_constraints(model, gp, x, b, passenger_index)
    with progress.phase("milp_v1.add_passenger_alighting_constraints"):
        _add_alighting_constraints(model, gp, x, e, passenger_index, discrete_scenario.cabin_capacity)
    with progress.phase("milp_v1.add_passenger_onboard_constraints"):
        _add_onboard_constraints(
            model,
            gp,
            b,
            z,
            e,
            passenger_index,
            active_cabin_ids,
            destinations,
            discrete_scenario.cabin_capacity,
            config.horizon_steps,
        )

    with progress.phase(f"milp_v1.optimize_{config.objective.value}"):
        if config.objective is MilpV1PassengerWaitingObjective.FEASIBILITY:
            model.setObjective(0.0, GRB.MINIMIZE)
        elif config.objective is MilpV1PassengerWaitingObjective.WAITING_TIME:
            model.setObjective(
                gp.quicksum(
                    q[time_step, origin, destination] * discrete_scenario.delta_seconds / 3600
                    for time_step in range(config.horizon_steps)
                    for origin, destination in passenger_index.od_pairs
                ),
                GRB.MINIMIZE,
            )
        else:
            raise NotImplementedError(f"MILP v1 objective {config.objective.value!r} is not implemented")
        model.optimize()

    status = _status_name(GRB, model.Status)
    objective_value = model.ObjVal if model.SolCount > 0 else None
    movement_variable_count = len(variable_index.x_keys) + len(variable_index.y_keys)
    passenger_variable_count = len(q_keys) + len(b_keys) + len(z_keys) + len(e_keys)
    empty_metadata = MilpPassengerWaitingMetadata(
        status=status,
        objective_value=objective_value,
        objective_passenger_hours=None,
        selected_arc_ids_by_cabin={},
        queue_count_by_time_od={},
        boarded_count_by_cabin_time_od={},
        onboard_count_by_cabin_time_destination={},
        alighted_count_by_cabin_time_destination={},
        total_boarded=0,
        total_alighted=0,
        total_unserved_at_horizon=0,
        total_onboard_at_horizon=0,
        movement_variable_count=movement_variable_count,
        passenger_variable_count=passenger_variable_count,
        constraint_count=model.NumConstrs,
    )
    if model.SolCount == 0:
        return MilpPassengerWaitingResult(movement_plan=None, metadata=empty_metadata)

    with progress.phase("milp_v1.extract_movement_solution"):
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
    with progress.phase("milp_v1.validate_movement_solution"):
        validation = validate_optimized_movement_plan(
            discrete_scenario,
            movement_plan,
            fixed_starts=config.fixed_starts,
            selected_arc_ids_by_cabin=selected_arc_ids_by_cabin,
        )
        validation.raise_for_errors()

    with progress.phase("milp_v1.extract_passenger_solution"):
        queue_counts = _integer_solution_values(model, q, q_keys)
        boarded_counts = _positive_integer_solution_values(model, b, b_keys)
        onboard_counts = _integer_solution_values(model, z, z_keys)
        alighted_counts = _positive_integer_solution_values(model, e, e_keys)

    objective_passenger_hours = sum(
        queue_counts[time_step, origin, destination] * discrete_scenario.delta_seconds / 3600
        for time_step in range(config.horizon_steps)
        for origin, destination in passenger_index.od_pairs
    )
    total_boarded = sum(boarded_counts.values())
    total_alighted = sum(alighted_counts.values())
    total_unserved_at_horizon = sum(
        queue_counts[config.horizon_steps, origin, destination]
        for origin, destination in passenger_index.od_pairs
    )
    total_onboard_at_horizon = sum(
        onboard_counts[cabin_id, config.horizon_steps, destination]
        for cabin_id in active_cabin_ids
        for destination in destinations
    )

    return MilpPassengerWaitingResult(
        movement_plan=movement_plan,
        metadata=MilpPassengerWaitingMetadata(
            status=status,
            objective_value=objective_value,
            objective_passenger_hours=objective_passenger_hours,
            selected_arc_ids_by_cabin=selected_arc_ids_by_cabin,
            queue_count_by_time_od=queue_counts,
            boarded_count_by_cabin_time_od=boarded_counts,
            onboard_count_by_cabin_time_destination=onboard_counts,
            alighted_count_by_cabin_time_destination=alighted_counts,
            total_boarded=total_boarded,
            total_alighted=total_alighted,
            total_unserved_at_horizon=total_unserved_at_horizon,
            total_onboard_at_horizon=total_onboard_at_horizon,
            movement_variable_count=movement_variable_count,
            passenger_variable_count=passenger_variable_count,
            constraint_count=model.NumConstrs,
        ),
    )


def _movement_config(config: MilpV1PassengerWaitingConfig) -> MilpV0Config:
    return MilpV0Config(
        horizon_steps=config.horizon_steps,
        fixed_starts=config.fixed_starts,
        allow_move_arcs=config.allow_move_arcs,
        allow_wait_arcs=config.allow_wait_arcs,
        allow_skip_arcs=config.allow_skip_arcs,
        variable_strategy=config.variable_strategy,
    )


def solve_milp_v1_passenger_waiting_feasibility(
    discrete_scenario: DiscreteScenario,
    config: MilpV1PassengerWaitingConfig,
    *,
    progress: ProgressReporter | None = None,
) -> MilpPassengerWaitingResult:
    config = MilpV1PassengerWaitingConfig(
        horizon_steps=config.horizon_steps,
        fixed_starts=config.fixed_starts,
        allow_move_arcs=config.allow_move_arcs,
        allow_wait_arcs=config.allow_wait_arcs,
        allow_skip_arcs=config.allow_skip_arcs,
        variable_strategy=config.variable_strategy,
        objective=MilpV1PassengerWaitingObjective.FEASIBILITY,
    )
    return solve_milp_v1_passenger_waiting(discrete_scenario, config, progress=progress)


def _add_queue_constraints(model, gp, q, b, passenger_index, active_cabin_ids: tuple[int, ...], horizon_steps: int) -> None:
    for origin, destination in passenger_index.od_pairs:
        for time_step in range(horizon_steps + 1):
            demand_count = passenger_index.demand_count_by_time_od.get((time_step, origin, destination), 0)
            boarded = gp.quicksum(
                b[cabin_id, time_step, origin, destination]
                for cabin_id in active_cabin_ids
                if (cabin_id, time_step, origin, destination) in b
            )
            if time_step == 0:
                model.addConstr(
                    q[time_step, origin, destination] == demand_count - boarded,
                    name=f"queue_balance[{time_step},{origin},{destination}]",
                )
            else:
                model.addConstr(
                    q[time_step, origin, destination]
                    == q[time_step - 1, origin, destination] + demand_count - boarded,
                    name=f"queue_balance[{time_step},{origin},{destination}]",
                )


def _add_boarding_constraints(model, gp, x, b, passenger_index) -> None:
    for (cabin_id, time_step, origin, destination), node_ids in passenger_index.boarding_candidates_by_cabin_time_od.items():
        model.addConstr(
            b[cabin_id, time_step, origin, destination]
            <= passenger_index.total_demand_by_od[origin, destination]
            * gp.quicksum(x[cabin_id, time_step, node_id] for node_id in node_ids),
            name=f"boarding_at_origin[{cabin_id},{time_step},{origin},{destination}]",
        )


def _add_alighting_constraints(model, gp, x, e, passenger_index, cabin_capacity: int) -> None:
    for (cabin_id, time_step, destination), node_ids in (
        passenger_index.alighting_candidates_by_cabin_time_destination.items()
    ):
        model.addConstr(
            e[cabin_id, time_step, destination]
            <= cabin_capacity * gp.quicksum(x[cabin_id, time_step, node_id] for node_id in node_ids),
            name=f"alighting_at_destination[{cabin_id},{time_step},{destination}]",
        )


def _add_onboard_constraints(
    model,
    gp,
    b,
    z,
    e,
    passenger_index,
    active_cabin_ids: tuple[int, ...],
    destinations: tuple[str, ...],
    cabin_capacity: int,
    horizon_steps: int,
) -> None:
    origins_by_destination = {
        destination: tuple(origin for origin, od_destination in passenger_index.od_pairs if od_destination == destination)
        for destination in destinations
    }
    for cabin_id in active_cabin_ids:
        for time_step in range(horizon_steps + 1):
            model.addConstr(
                gp.quicksum(z[cabin_id, time_step, destination] for destination in destinations) <= cabin_capacity,
                name=f"cabin_capacity[{cabin_id},{time_step}]",
            )
            for destination in destinations:
                boarded_to_destination = gp.quicksum(
                    b[cabin_id, time_step, origin, destination]
                    for origin in origins_by_destination[destination]
                    if (cabin_id, time_step, origin, destination) in b
                )
                alighted = e[cabin_id, time_step, destination] if (cabin_id, time_step, destination) in e else 0
                previous_onboard = z[cabin_id, time_step - 1, destination] if time_step > 0 else 0
                model.addConstr(
                    z[cabin_id, time_step, destination]
                    == previous_onboard + boarded_to_destination - alighted,
                    name=f"onboard_balance[{cabin_id},{time_step},{destination}]",
                )
                model.addConstr(
                    alighted <= previous_onboard + boarded_to_destination,
                    name=f"alighting_available[{cabin_id},{time_step},{destination}]",
                )
        for destination in destinations:
            model.addConstr(
                z[cabin_id, horizon_steps, destination] == 0,
                name=f"empty_at_horizon[{cabin_id},{destination}]",
            )


def _integer_solution_values(model, variables, keys) -> dict:
    if not keys:
        return {}
    values = model.getAttr("X", [variables[key] for key in keys])
    return {
        key: int(round(value))
        for key, value in zip(keys, values, strict=True)
    }


def _positive_integer_solution_values(model, variables, keys) -> dict:
    return {
        key: value
        for key, value in _integer_solution_values(model, variables, keys).items()
        if value > 0
    }
