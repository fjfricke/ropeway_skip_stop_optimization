import type { Scenario, TrackSegment } from "../../types";
import { lineViewLinks, lineViewStations, stationLabel } from "../LineViewLayer";
import type { ScenarioDisplayMode } from "../viewerTypes";

export type ExportItemOption = {
  id: string;
  label: string;
};

export function exportNodeOptions(scenario: Scenario, displayMode: ScenarioDisplayMode): ExportItemOption[] {
  if (displayMode === "line") {
    return lineViewStations(scenario).map((station) => ({
      id: station.id,
      label: stationLabel(station),
    }));
  }
  return scenario.physical_nodes.map((node) => ({
    id: node.id,
    label: node.id.replaceAll("_", " "),
  }));
}

export function exportArcOptions(scenario: Scenario, displayMode: ScenarioDisplayMode): ExportItemOption[] {
  if (displayMode === "line") {
    return lineViewLinks(scenario, { x: 0, y: 0, width: 1, height: 1 }).map(({ id, from, to }) => ({
      id,
      label: `${stationLabel(from.station)} -> ${stationLabel(to.station)}`,
    }));
  }
  return scenario.track_segments.map((segment) => ({
    id: segment.id,
    label: physicalArcLabel(segment),
  }));
}

export function physicalArcLabel(segment: TrackSegment) {
  return `${segment.id.replaceAll("_", " ")} (${segment.from_node_id} -> ${segment.to_node_id})`;
}

export function toggleId(ids: string[], id: string) {
  return ids.includes(id) ? ids.filter((current) => current !== id) : [...ids, id];
}
