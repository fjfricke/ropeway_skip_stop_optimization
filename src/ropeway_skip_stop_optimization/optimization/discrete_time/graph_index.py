from __future__ import annotations

from dataclasses import dataclass

from ropeway_skip_stop_optimization.models import DiscreteArc, DiscreteNode, DiscreteScenario


@dataclass(frozen=True)
class DiscreteGraphIndex:
    nodes_by_id: dict[str, DiscreteNode]
    arcs_by_id: dict[str, DiscreteArc]
    out_arc_ids_by_node_id: dict[str, tuple[str, ...]]
    in_arc_ids_by_node_id: dict[str, tuple[str, ...]]
    arc_ids_by_endpoints: dict[tuple[str, str], tuple[str, ...]]


def build_discrete_graph_index(discrete_scenario: DiscreteScenario) -> DiscreteGraphIndex:
    nodes_by_id = _unique_by_id("discrete node", discrete_scenario.nodes)
    arcs_by_id = _unique_by_id("discrete arc", discrete_scenario.arcs)

    out_arc_ids_by_node_id: dict[str, list[str]] = {node_id: [] for node_id in nodes_by_id}
    in_arc_ids_by_node_id: dict[str, list[str]] = {node_id: [] for node_id in nodes_by_id}
    arc_ids_by_endpoints: dict[tuple[str, str], list[str]] = {}

    for arc in discrete_scenario.arcs:
        if arc.from_node_id not in nodes_by_id:
            raise ValueError(f"arc {arc.id!r} references unknown from_node_id {arc.from_node_id!r}")
        if arc.to_node_id not in nodes_by_id:
            raise ValueError(f"arc {arc.id!r} references unknown to_node_id {arc.to_node_id!r}")
        out_arc_ids_by_node_id[arc.from_node_id].append(arc.id)
        in_arc_ids_by_node_id[arc.to_node_id].append(arc.id)
        arc_ids_by_endpoints.setdefault((arc.from_node_id, arc.to_node_id), []).append(arc.id)

    return DiscreteGraphIndex(
        nodes_by_id=nodes_by_id,
        arcs_by_id=arcs_by_id,
        out_arc_ids_by_node_id={node_id: tuple(arc_ids) for node_id, arc_ids in out_arc_ids_by_node_id.items()},
        in_arc_ids_by_node_id={node_id: tuple(arc_ids) for node_id, arc_ids in in_arc_ids_by_node_id.items()},
        arc_ids_by_endpoints={
            endpoints: tuple(arc_ids)
            for endpoints, arc_ids in arc_ids_by_endpoints.items()
        },
    )


def _unique_by_id(label: str, items):
    result = {}
    duplicates = set()
    for item in items:
        if item.id in result:
            duplicates.add(item.id)
        result[item.id] = item
    if duplicates:
        raise ValueError(f"duplicate {label} ids: {duplicates}")
    return result
