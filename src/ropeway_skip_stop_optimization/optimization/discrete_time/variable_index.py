from __future__ import annotations

from collections import defaultdict

from ropeway_skip_stop_optimization.optimization.discrete_time.graph_index import DiscreteGraphIndex
from ropeway_skip_stop_optimization.optimization.discrete_time.models import FixedCabinStart, MilpV0VariableIndex
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
    allowed_out_arc_ids_by_node_id = _allowed_out_arc_ids_by_node_id(graph_index, allowed_arc_id_set)
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
        (cabin_id, time_step, node_id): allowed_out_arc_ids_by_node_id[node_id]
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
    reachable_cabin_ids_by_time_node = {
        (time_step, node_id): cabin_ids
        for time_step in range(horizon_steps + 1)
        for node_id in node_ids
    }

    return MilpV0VariableIndex(
        x_keys=x_keys,
        y_keys=y_keys,
        node_ids_by_cabin_time=node_ids_by_cabin_time,
        arc_ids_by_cabin_time=arc_ids_by_cabin_time,
        out_arc_ids_by_cabin_time_node=out_arc_ids_by_cabin_time_node,
        in_arc_ids_by_cabin_time_node=in_arc_ids_by_cabin_time_node,
        reachable_cabin_ids_by_time_node=reachable_cabin_ids_by_time_node,
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
    allowed_out_arc_ids_by_node_id = _allowed_out_arc_ids_by_node_id(graph_index, allowed_arc_id_set)
    to_node_id_by_arc_id = {
        arc_id: graph_index.arcs_by_id[arc_id].to_node_id
        for arc_id in allowed_arc_ids
    }
    transition_cache: dict[tuple[str, ...], tuple[tuple[str, ...], tuple[str, ...], dict[str, tuple[str, ...]]]] = {}
    node_ids_by_cabin_time: dict[tuple[int, int], tuple[str, ...]] = {}
    arc_ids_by_cabin_time: dict[tuple[int, int], tuple[str, ...]] = {}
    out_arc_ids_by_cabin_time_node: dict[tuple[int, int, str], tuple[str, ...]] = {}
    in_arc_ids_by_cabin_time_node: dict[tuple[int, int, str], tuple[str, ...]] = {}
    reachable_cabin_ids_by_time_node_lists: dict[tuple[int, str], list[int]] = defaultdict(list)
    x_keys: list[tuple[int, int, str]] = []
    y_keys: list[tuple[int, int, str]] = []
    max_reachable_nodes = 0

    for start in progress.iter(fixed_starts, label="sparse reachability cabins", total=len(fixed_starts)):
        reachable_node_ids = (start.node_id,)
        if start.node_id not in graph_index.nodes_by_id:
            raise ValueError(f"sparse reachability start node {start.node_id!r} is unknown")

        node_ids_by_cabin_time[start.cabin_id, 0] = reachable_node_ids
        x_keys.append((start.cabin_id, 0, start.node_id))
        reachable_cabin_ids_by_time_node_lists[0, start.node_id].append(start.cabin_id)
        max_reachable_nodes = max(max_reachable_nodes, 1)

        for time_step in range(horizon_steps):
            transition = transition_cache.get(reachable_node_ids)
            if transition is None:
                next_node_ids: list[str] = []
                next_node_id_set: set[str] = set()
                next_in_arc_ids_by_node_id: dict[str, list[str]] = {}
                step_arc_ids: list[str] = []
                out_arc_ids_by_node_id = allowed_out_arc_ids_by_node_id
                to_node_id_by_arc = to_node_id_by_arc_id
                for node_id in reachable_node_ids:
                    out_arc_ids = out_arc_ids_by_node_id[node_id]
                    if not out_arc_ids:
                        raise ValueError(
                            f"sparse reachability hit dead-end node {node_id!r} at t={time_step}"
                        )
                    step_arc_ids.extend(out_arc_ids)
                    for arc_id in out_arc_ids:
                        to_node_id = to_node_id_by_arc[arc_id]
                        if to_node_id not in next_node_id_set:
                            next_node_id_set.add(to_node_id)
                            next_node_ids.append(to_node_id)
                            next_in_arc_ids_by_node_id[to_node_id] = [arc_id]
                        else:
                            next_in_arc_ids_by_node_id[to_node_id].append(arc_id)

                transition = (
                    tuple(next_node_ids),
                    tuple(step_arc_ids),
                    {
                        node_id: tuple(in_arc_ids)
                        for node_id, in_arc_ids in next_in_arc_ids_by_node_id.items()
                    },
                )
                transition_cache[reachable_node_ids] = transition
            next_node_ids_tuple, step_arc_ids_tuple, next_in_arc_ids_by_node_id_tuple = transition

            cabin_id = start.cabin_id
            for node_id in reachable_node_ids:
                out_arc_ids_by_cabin_time_node[cabin_id, time_step, node_id] = allowed_out_arc_ids_by_node_id[node_id]

            arc_ids_by_cabin_time[cabin_id, time_step] = step_arc_ids_tuple
            y_keys.extend((cabin_id, time_step, arc_id) for arc_id in step_arc_ids_tuple)
            reachable_node_ids = next_node_ids_tuple
            next_time_step = time_step + 1
            node_ids_by_cabin_time[cabin_id, next_time_step] = reachable_node_ids
            x_keys.extend((cabin_id, next_time_step, node_id) for node_id in reachable_node_ids)
            max_reachable_nodes = max(max_reachable_nodes, len(reachable_node_ids))
            for node_id in reachable_node_ids:
                reachable_cabin_ids_by_time_node_lists[next_time_step, node_id].append(cabin_id)
                in_arc_ids_by_cabin_time_node[cabin_id, next_time_step, node_id] = (
                    next_in_arc_ids_by_node_id_tuple[node_id]
                )

    if progress.enabled:
        progress.logger.info(
            "milp_v0.sparse_variable_index_counts: x=%d y=%d transitions=%d reachable_time_nodes=%d max_reachable_nodes=%d",
            len(x_keys),
            len(y_keys),
            len(transition_cache),
            len(reachable_cabin_ids_by_time_node_lists),
            max_reachable_nodes,
        )

    return MilpV0VariableIndex(
        x_keys=tuple(x_keys),
        y_keys=tuple(y_keys),
        node_ids_by_cabin_time=node_ids_by_cabin_time,
        arc_ids_by_cabin_time=arc_ids_by_cabin_time,
        out_arc_ids_by_cabin_time_node=out_arc_ids_by_cabin_time_node,
        in_arc_ids_by_cabin_time_node=in_arc_ids_by_cabin_time_node,
        reachable_cabin_ids_by_time_node={
            key: tuple(cabin_ids)
            for key, cabin_ids in reachable_cabin_ids_by_time_node_lists.items()
        },
    )


def _allowed_out_arc_ids_by_node_id(
    graph_index: DiscreteGraphIndex,
    allowed_arc_id_set: set[str],
) -> dict[str, tuple[str, ...]]:
    return {
        node_id: tuple(
            arc_id
            for arc_id in arc_ids
            if arc_id in allowed_arc_id_set
        )
        for node_id, arc_ids in graph_index.out_arc_ids_by_node_id.items()
    }
