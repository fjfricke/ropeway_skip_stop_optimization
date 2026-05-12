from __future__ import annotations

from ropeway_skip_stop_optimization.baselines import build_all_stop_cycle_path, greedy_place_max_cabins_on_cycle
from ropeway_skip_stop_optimization.examples.three_station import build_three_station_scenario
from ropeway_skip_stop_optimization.optimization.discrete_time import FixedCabinStart, build_discrete_graph_index
from ropeway_skip_stop_optimization.optimization.discrete_time.movement_model import _allowed_arc_ids
from ropeway_skip_stop_optimization.optimization.discrete_time.models import MilpV0Config
from ropeway_skip_stop_optimization.optimization.discrete_time.variable_index import (
    build_dense_milp_v0_variable_index,
    build_sparse_reachability_milp_v0_variable_index,
)
from ropeway_skip_stop_optimization.mapping import discretize_scenario


def test_dense_variable_index_matches_cartesian_variable_counts() -> None:
    discrete = discretize_scenario(build_three_station_scenario())
    path = build_all_stop_cycle_path(discrete)
    start_indices = greedy_place_max_cabins_on_cycle(discrete, path.node_ids)
    fixed_starts = tuple(
        FixedCabinStart(cabin_id=cabin_id, node_id=path.node_ids[start_index])
        for cabin_id, start_index in enumerate(start_indices[:23])
    )
    config = MilpV0Config(horizon_steps=60, fixed_starts=fixed_starts)
    graph_index = build_discrete_graph_index(discrete)
    allowed_arc_ids = _allowed_arc_ids(discrete, config)

    variable_index = build_dense_milp_v0_variable_index(
        graph_index,
        fixed_starts,
        allowed_arc_ids,
        config.horizon_steps,
    )

    assert len(variable_index.x_keys) == 23 * 61 * 406
    assert len(variable_index.y_keys) == 23 * 60 * 410
    assert len(variable_index.x_keys) + len(variable_index.y_keys) == 1_135_418


def test_dense_variable_index_has_full_node_and_arc_sets_for_each_cabin_time() -> None:
    discrete = discretize_scenario(build_three_station_scenario())
    graph_index = build_discrete_graph_index(discrete)
    config = MilpV0Config(horizon_steps=2, fixed_starts=(FixedCabinStart(cabin_id=7, node_id=discrete.nodes[0].id),))
    allowed_arc_ids = _allowed_arc_ids(discrete, config)

    variable_index = build_dense_milp_v0_variable_index(
        graph_index,
        config.fixed_starts,
        allowed_arc_ids,
        config.horizon_steps,
    )

    assert variable_index.node_ids_by_cabin_time[7, 0] == tuple(graph_index.nodes_by_id)
    assert variable_index.node_ids_by_cabin_time[7, 2] == tuple(graph_index.nodes_by_id)
    assert variable_index.arc_ids_by_cabin_time[7, 0] == allowed_arc_ids
    assert variable_index.arc_ids_by_cabin_time[7, 1] == allowed_arc_ids
    assert variable_index.reachable_cabin_ids_by_time_node[0, discrete.nodes[0].id] == (7,)
    assert variable_index.reachable_cabin_ids_by_time_node[2, discrete.nodes[-1].id] == (7,)
    for node_id in graph_index.nodes_by_id:
        assert variable_index.out_arc_ids_by_cabin_time_node[7, 0, node_id] == graph_index.out_arc_ids_by_node_id[node_id]
        assert variable_index.in_arc_ids_by_cabin_time_node[7, 1, node_id] == graph_index.in_arc_ids_by_node_id[node_id]


def test_sparse_reachability_index_starts_at_fixed_start_and_follows_directed_arcs() -> None:
    discrete = discretize_scenario(build_three_station_scenario())
    path = build_all_stop_cycle_path(discrete)
    graph_index = build_discrete_graph_index(discrete)
    config = MilpV0Config(horizon_steps=2, fixed_starts=(FixedCabinStart(cabin_id=3, node_id=path.node_ids[0]),))
    allowed_arc_ids = _allowed_arc_ids(discrete, config)

    variable_index = build_sparse_reachability_milp_v0_variable_index(
        graph_index,
        config.fixed_starts,
        allowed_arc_ids,
        config.horizon_steps,
    )

    assert variable_index.node_ids_by_cabin_time[3, 0] == (path.node_ids[0],)
    assert set(variable_index.node_ids_by_cabin_time[3, 1]) == {
        graph_index.arcs_by_id[arc_id].to_node_id
        for arc_id in graph_index.out_arc_ids_by_node_id[path.node_ids[0]]
    }
    for arc_id in variable_index.arc_ids_by_cabin_time[3, 0]:
        assert graph_index.arcs_by_id[arc_id].from_node_id == path.node_ids[0]
    assert variable_index.reachable_cabin_ids_by_time_node[0, path.node_ids[0]] == (3,)
    for node_id in variable_index.node_ids_by_cabin_time[3, 1]:
        assert variable_index.reachable_cabin_ids_by_time_node[1, node_id] == (3,)


def test_sparse_reachability_index_is_subset_of_dense_index() -> None:
    discrete = discretize_scenario(build_three_station_scenario())
    path = build_all_stop_cycle_path(discrete)
    graph_index = build_discrete_graph_index(discrete)
    config = MilpV0Config(horizon_steps=10, fixed_starts=(FixedCabinStart(cabin_id=0, node_id=path.node_ids[0]),))
    allowed_arc_ids = _allowed_arc_ids(discrete, config)

    dense_index = build_dense_milp_v0_variable_index(
        graph_index,
        config.fixed_starts,
        allowed_arc_ids,
        config.horizon_steps,
    )
    sparse_index = build_sparse_reachability_milp_v0_variable_index(
        graph_index,
        config.fixed_starts,
        allowed_arc_ids,
        config.horizon_steps,
    )

    assert set(sparse_index.x_keys) < set(dense_index.x_keys)
    assert set(sparse_index.y_keys) < set(dense_index.y_keys)
