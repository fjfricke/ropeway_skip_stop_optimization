import type { ScenarioLayout } from "../scenarioLayout";
import type { Scenario } from "../types";

export function stationZoneBounds(stationId: string, scenario: Scenario, layout: ScenarioLayout) {
  const stationNodeIds = new Set(scenario.physical_nodes.filter((node) => node.station_id === stationId).map((node) => node.id));
  for (const route of scenario.station_routes) {
    if (route.station_id !== stationId) continue;
    for (const segmentId of route.segment_ids) {
      const segment = scenario.track_segments.find((current) => current.id === segmentId);
      if (!segment) continue;
      stationNodeIds.add(segment.from_node_id);
      stationNodeIds.add(segment.to_node_id);
    }
  }

  const points = [...stationNodeIds].flatMap((nodeId) => {
    const point = layout.nodes[nodeId];
    return point ? [point] : [];
  });
  if (points.length === 0) return null;
  return {
    minX: Math.min(...points.map((point) => point.x)),
    minY: Math.min(...points.map((point) => point.y)),
    maxX: Math.max(...points.map((point) => point.x)),
    maxY: Math.max(...points.map((point) => point.y)),
  };
}
