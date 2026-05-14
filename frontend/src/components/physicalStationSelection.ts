import type { Scenario, TrackSegment } from "../types";

export function stationIdsForPhysicalContent({
  scenario,
  nodeIds,
  segments,
}: {
  scenario: Scenario;
  nodeIds: Iterable<string>;
  segments: Iterable<TrackSegment>;
}) {
  const stationIds = new Set<string>();
  const selectedNodeIds = new Set(nodeIds);
  const nodeById = new Map(scenario.physical_nodes.map((node) => [node.id, node]));

  for (const node of scenario.physical_nodes) {
    if (node.station_id && selectedNodeIds.has(node.id)) stationIds.add(node.station_id);
  }
  for (const segment of segments) {
    const from = nodeById.get(segment.from_node_id);
    const to = nodeById.get(segment.to_node_id);
    if (from?.station_id) stationIds.add(from.station_id);
    if (to?.station_id) stationIds.add(to.station_id);
  }
  return stationIds;
}
