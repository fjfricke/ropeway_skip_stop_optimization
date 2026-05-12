from __future__ import annotations

from ropeway_skip_stop_optimization.models import (
    CabinPosition,
    CabinTrajectory,
    DiscreteConstraintStrength,
    DiscreteScenario,
    MovementPlan,
)
from ropeway_skip_stop_optimization.optimization.graph_index import DiscreteGraphIndex
from ropeway_skip_stop_optimization.optimization.models import MilpV0VariableIndex
from ropeway_skip_stop_optimization.progress import ProgressReporter


def create_movement_variables(
    model,
    grb,
    variable_index: MilpV0VariableIndex,
):
    x = model.addVars(variable_index.x_keys, vtype=grb.BINARY, name="x")
    y = model.addVars(variable_index.y_keys, vtype=grb.BINARY, name="y")
    return x, y


def add_position_constraints(
    model,
    gp,
    x,
    variable_index: MilpV0VariableIndex,
    active_cabin_ids: tuple[int, ...],
    horizon_steps: int,
    *,
    progress: ProgressReporter,
) -> None:
    for cabin_id in progress.iter(active_cabin_ids, label="position constraints", total=len(active_cabin_ids)):
        for time_step in range(horizon_steps + 1):
            model.addConstr(
                gp.quicksum(
                    x[cabin_id, time_step, node_id]
                    for node_id in variable_index.node_ids_by_cabin_time[cabin_id, time_step]
                )
                == 1,
                name=f"position_once[{cabin_id},{time_step}]",
            )


def add_flow_constraints(
    model,
    gp,
    x,
    y,
    variable_index: MilpV0VariableIndex,
    *,
    progress: ProgressReporter,
) -> None:
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


def add_initial_constraints(
    model,
    x,
    fixed_start_by_cabin: dict[int, str],
) -> None:
    for cabin_id, node_id in fixed_start_by_cabin.items():
        model.addConstr(x[cabin_id, 0, node_id] == 1, name=f"initial[{cabin_id}]")


def add_conflict_constraints(
    model,
    gp,
    x,
    discrete_scenario: DiscreteScenario,
    graph_index: DiscreteGraphIndex,
    variable_index: MilpV0VariableIndex,
    horizon_steps: int,
) -> None:
    hard_node_constraints = tuple(
        constraint
        for constraint in discrete_scenario.constraints
        if constraint.strength is DiscreteConstraintStrength.HARD and constraint.node_ids
    )
    for time_step in range(horizon_steps + 1):
        for node_id in graph_index.nodes_by_id:
            participant_cabin_ids = variable_index.reachable_cabin_ids_by_time_node.get((time_step, node_id), ())
            if len(participant_cabin_ids) < 2:
                continue
            participants = [x[cabin_id, time_step, node_id] for cabin_id in participant_cabin_ids]
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


def extract_movement_plan(
    model,
    x,
    y,
    variable_index: MilpV0VariableIndex,
    discrete_scenario_id: str,
    active_cabin_ids: tuple[int, ...],
    horizon_steps: int,
    *,
    progress: ProgressReporter,
) -> tuple[MovementPlan, dict[int, tuple[str, ...]]]:
    selected_arc_ids_by_cabin: dict[int, tuple[str, ...]] = {}
    trajectories: list[CabinTrajectory] = []
    for cabin_id in progress.iter(active_cabin_ids, label="extract solution", total=len(active_cabin_ids)):
        selected_node_id_by_time = _selected_nodes_by_time(
            model,
            x,
            variable_index.node_ids_by_cabin_time,
            cabin_id,
            horizon_steps,
        )
        selected_arc_id_by_time = _selected_arcs_by_time(
            model,
            y,
            variable_index.arc_ids_by_cabin_time,
            cabin_id,
            horizon_steps,
        )
        positions: list[CabinPosition] = []
        selected_arc_ids: list[str] = []
        for time_step in range(horizon_steps + 1):
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
            if time_step < horizon_steps:
                selected_arc_ids.append(selected_arc_id_by_time[time_step])
        selected_arc_ids_by_cabin[cabin_id] = tuple(selected_arc_ids)
        trajectories.append(CabinTrajectory(cabin_id=cabin_id, positions=tuple(positions)))

    return (
        MovementPlan(
            discrete_scenario_id=discrete_scenario_id,
            horizon_steps=horizon_steps,
            trajectories=tuple(trajectories),
        ),
        selected_arc_ids_by_cabin,
    )


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
