from __future__ import annotations

from dataclasses import replace

from ropeway_skip_stop_optimization.examples import build_three_station_scenario
from ropeway_skip_stop_optimization.optimization import build_discrete_graph_index
from ropeway_skip_stop_optimization.preprocessing.discretize import discretize_scenario


def test_discrete_graph_index_builds_incidence_lookups() -> None:
    discrete = discretize_scenario(build_three_station_scenario())

    index = build_discrete_graph_index(discrete)

    assert set(index.nodes_by_id) == {node.id for node in discrete.nodes}
    assert set(index.arcs_by_id) == {arc.id for arc in discrete.arcs}
    for arc in discrete.arcs:
        assert arc.id in index.out_arc_ids_by_node_id[arc.from_node_id]
        assert arc.id in index.in_arc_ids_by_node_id[arc.to_node_id]
        assert arc.id in index.arc_ids_by_endpoints[(arc.from_node_id, arc.to_node_id)]


def test_discrete_graph_index_rejects_duplicate_node_ids() -> None:
    discrete = discretize_scenario(build_three_station_scenario())
    duplicate_node = discrete.nodes[0]
    bad_discrete = replace(discrete, nodes=discrete.nodes + (duplicate_node,))

    try:
        build_discrete_graph_index(bad_discrete)
    except ValueError as error:
        assert "duplicate discrete node ids" in str(error)
    else:
        raise AssertionError("expected duplicate node ids to fail")


def test_discrete_graph_index_rejects_dangling_arc_endpoint() -> None:
    discrete = discretize_scenario(build_three_station_scenario())
    bad_arc = replace(discrete.arcs[0], to_node_id="missing")
    bad_discrete = replace(discrete, arcs=(bad_arc, *discrete.arcs[1:]))

    try:
        build_discrete_graph_index(bad_discrete)
    except ValueError as error:
        assert "unknown to_node_id" in str(error)
    else:
        raise AssertionError("expected dangling arc endpoint to fail")
