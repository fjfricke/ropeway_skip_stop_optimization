from __future__ import annotations

from ropeway_skip_stop_optimization.optimization.graph_index import DiscreteGraphIndex
from ropeway_skip_stop_optimization.optimization.models import FixedCabinStart, MilpV0VariableIndex
from ropeway_skip_stop_optimization.progress import ProgressReporter


def build_dense_milp_v0_variable_index(
    graph_index: DiscreteGraphIndex,
    fixed_starts: tuple[FixedCabinStart, ...],
    allowed_arc_ids: tuple[str, ...],
    horizon_steps: int,
) -> MilpV0VariableIndex:
    cabin_ids = tuple(start.cabin_id for start in fixed_starts)
    node_ids = tuple(graph_index.nodes_by_id)
    allowed_arc_id_set = set(allowed_arc_ids)
    x_keys = tuple(
        (cabin_id, time_step, node_id)
        for cabin_id in cabin_ids
        for time_step in range(horizon_steps + 1)
        for node_id in node_ids
    )
    y_keys = tuple(
        (cabin_id, time_step, arc_id)
        for cabin_id in cabin_ids
        for time_step in range(horizon_steps)
        for arc_id in allowed_arc_ids
    )

    node_ids_by_cabin_time = {
        (cabin_id, time_step): node_ids
        for cabin_id in cabin_ids
        for time_step in range(horizon_steps + 1)
    }
    arc_ids_by_cabin_time = {
        (cabin_id, time_step): allowed_arc_ids
        for cabin_id in cabin_ids
        for time_step in range(horizon_steps)
    }
    out_arc_ids_by_cabin_time_node = {
        (cabin_id, time_step, node_id): tuple(
            arc_id
            for arc_id in graph_index.out_arc_ids_by_node_id[node_id]
            if arc_id in allowed_arc_id_set
        )
        for cabin_id in cabin_ids
        for time_step in range(horizon_steps)
        for node_id in node_ids
    }
    in_arc_ids_by_cabin_time_node = {
        (cabin_id, time_step, node_id): tuple(
            arc_id
            for arc_id in graph_index.in_arc_ids_by_node_id[node_id]
            if arc_id in allowed_arc_id_set
        )
        for cabin_id in cabin_ids
        for time_step in range(1, horizon_steps + 1)
        for node_id in node_ids
    }

    return MilpV0VariableIndex(
        x_keys=x_keys,
        y_keys=y_keys,
        node_ids_by_cabin_time=node_ids_by_cabin_time,
        arc_ids_by_cabin_time=arc_ids_by_cabin_time,
        out_arc_ids_by_cabin_time_node=out_arc_ids_by_cabin_time_node,
        in_arc_ids_by_cabin_time_node=in_arc_ids_by_cabin_time_node,
    )


def build_sparse_reachability_milp_v0_variable_index(
    graph_index: DiscreteGraphIndex,
    fixed_starts: tuple[FixedCabinStart, ...],
    allowed_arc_ids: tuple[str, ...],
    horizon_steps: int,
    *,
    progress: ProgressReporter | None = None,
) -> MilpV0VariableIndex:
    progress = progress or ProgressReporter()
    allowed_arc_id_set = set(allowed_arc_ids)
    node_ids_by_cabin_time: dict[tuple[int, int], tuple[str, ...]] = {}
    arc_ids_by_cabin_time: dict[tuple[int, int], tuple[str, ...]] = {}
    out_arc_ids_by_cabin_time_node: dict[tuple[int, int, str], tuple[str, ...]] = {}
    in_arc_ids_by_cabin_time_node: dict[tuple[int, int, str], tuple[str, ...]] = {}
    x_keys: list[tuple[int, int, str]] = []
    y_keys: list[tuple[int, int, str]] = []

    for start in progress.iter(fixed_starts, label="sparse reachability cabins", total=len(fixed_starts)):
        reachable_node_ids = (start.node_id,)
        if start.node_id not in graph_index.nodes_by_id:
            raise ValueError(f"sparse reachability start node {start.node_id!r} is unknown")

        node_ids_by_cabin_time[start.cabin_id, 0] = reachable_node_ids
        x_keys.append((start.cabin_id, 0, start.node_id))

        for time_step in range(horizon_steps):
            next_node_ids: list[str] = []
            next_in_arc_ids_by_node_id: dict[str, list[str]] = {}
            step_arc_ids: list[str] = []
            for node_id in reachable_node_ids:
                out_arc_ids = tuple(
                    arc_id
                    for arc_id in graph_index.out_arc_ids_by_node_id[node_id]
                    if arc_id in allowed_arc_id_set
                )
                if not out_arc_ids:
                    raise ValueError(
                        f"sparse reachability hit dead-end node {node_id!r} for cabin "
                        f"{start.cabin_id!r} at t={time_step}"
                    )
                out_arc_ids_by_cabin_time_node[start.cabin_id, time_step, node_id] = out_arc_ids
                for arc_id in out_arc_ids:
                    arc = graph_index.arcs_by_id[arc_id]
                    step_arc_ids.append(arc_id)
                    if arc.to_node_id not in next_in_arc_ids_by_node_id:
                        next_node_ids.append(arc.to_node_id)
                        next_in_arc_ids_by_node_id[arc.to_node_id] = []
                    next_in_arc_ids_by_node_id[arc.to_node_id].append(arc_id)

            arc_ids_by_cabin_time[start.cabin_id, time_step] = tuple(dict.fromkeys(step_arc_ids))
            y_keys.extend((start.cabin_id, time_step, arc_id) for arc_id in arc_ids_by_cabin_time[start.cabin_id, time_step])
            reachable_node_ids = tuple(next_node_ids)
            node_ids_by_cabin_time[start.cabin_id, time_step + 1] = reachable_node_ids
            x_keys.extend((start.cabin_id, time_step + 1, node_id) for node_id in reachable_node_ids)
            for node_id, in_arc_ids in next_in_arc_ids_by_node_id.items():
                in_arc_ids_by_cabin_time_node[start.cabin_id, time_step + 1, node_id] = tuple(in_arc_ids)

    return MilpV0VariableIndex(
        x_keys=tuple(x_keys),
        y_keys=tuple(y_keys),
        node_ids_by_cabin_time=node_ids_by_cabin_time,
        arc_ids_by_cabin_time=arc_ids_by_cabin_time,
        out_arc_ids_by_cabin_time_node=out_arc_ids_by_cabin_time_node,
        in_arc_ids_by_cabin_time_node=in_arc_ids_by_cabin_time_node,
    )
