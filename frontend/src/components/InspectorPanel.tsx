import { Info } from "lucide-react";
import type { DiscreteScenario, Scenario, Selection, SpeedProfile } from "../types";
import type { DiscreteOverlayMode, DiscreteViewerToggles } from "./ScenarioViewer";

interface InspectorPanelProps {
  scenario: Scenario;
  discreteScenario: DiscreteScenario | null;
  selection: Selection | null;
  discreteMode: DiscreteOverlayMode;
  discreteToggles: DiscreteViewerToggles;
}

export function InspectorPanel({ scenario, discreteScenario, selection, discreteMode, discreteToggles }: InspectorPanelProps) {
  const content = selection ? resolveSelection(scenario, discreteScenario, selection, discreteMode, discreteToggles) : null;

  return (
    <section className="panel inspector-panel">
      <header className="panel__header">
        <Info size={17} />
        <h2>Inspector</h2>
      </header>
      {content ? (
        <div className="kv-list">
          <h3>{content.title}</h3>
          {content.rows.map((row) => (
            <div className={`kv-row ${"tone" in row ? `kv-row--${row.tone}` : ""}`} key={row.label}>
              <span>{row.label}</span>
              <strong>{row.value}</strong>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty-panel">No selection</div>
      )}
    </section>
  );
}

function resolveSelection(
  scenario: Scenario,
  discreteScenario: DiscreteScenario | null,
  selection: Selection,
  discreteMode: DiscreteOverlayMode,
  discreteToggles: DiscreteViewerToggles,
) {
  if (selection.type === "node") {
    const node = scenario.physical_nodes.find((item) => item.id === selection.id);
    if (!node) return null;
    return {
      title: node.id,
      rows: [
        { label: "type", value: node.kind },
        { label: "station", value: node.station_id ?? "none" },
        { label: "waiting", value: node.allows_waiting ? "yes" : "no" },
      ],
    };
  }

  if (selection.type === "segment") {
    const segment = scenario.track_segments.find((item) => item.id === selection.id);
    if (!segment) return null;
    const route = scenario.station_routes.find((item) => item.segment_ids.includes(segment.id));
    const discreteRows = discreteScenario
      ? discreteSegmentRows(discreteScenario, segment.id, discreteMode, discreteToggles)
      : [{ label: "discrete", value: "not loaded" }];
    return {
      title: segment.id,
      rows: [
        { label: "type", value: segment.kind },
        { label: "from", value: segment.from_node_id },
        { label: "to", value: segment.to_node_id },
        { label: "length", value: `${segment.length_m} m` },
        { label: "speed", value: speedProfileLabel(segment.speed_profile) },
        { label: "resource", value: segment.resource_id ?? "none" },
        { label: "route", value: route ? `${route.id} (${route.kind})` : "main rope" },
        ...discreteRows,
      ],
    };
  }

  if (selection.type === "discrete_node") {
    const node = discreteScenario?.nodes.find((item) => item.id === selection.id);
    if (!node) return null;
    return {
      title: node.id,
      rows: [
        { label: "type", value: node.source_physical_node_id ? "physical node" : "segment position" },
        { label: "physical", value: node.source_physical_node_id ?? "none" },
        { label: "segment", value: node.source_segment_id ?? "none" },
        { label: "position", value: node.position_m === null ? "n/a" : `${roundOne(node.position_m)} m` },
        { label: "station", value: node.station_id ?? "none" },
        { label: "waiting", value: node.allows_waiting ? "yes" : "no" },
      ],
    };
  }

  if (selection.type === "discrete_arc") {
    const arc = discreteScenario?.arcs.find((item) => item.id === selection.id);
    if (!arc) return null;
    return {
      title: arc.id,
      rows: [
        { label: "kind", value: arc.kind },
        { label: "from", value: arc.from_node_id },
        { label: "to", value: arc.to_node_id },
        { label: "segment", value: arc.source_segment_id ?? "none" },
        { label: "route", value: arc.source_route_id ?? "none" },
      ],
    };
  }

  if (selection.type === "discrete_constraint") {
    const constraint = discreteScenario?.constraints.find((item) => item.id === selection.id);
    if (!constraint) return null;
    return {
      title: constraint.id,
      rows: [
        { label: "kind", value: constraint.kind },
        { label: "scope", value: constraint.scope },
        { label: "strength", value: constraint.strength },
        { label: "nodes", value: constraint.node_ids.join(" | ") },
        { label: "segments", value: constraint.source_segment_ids.join(" | ") || "none" },
        { label: "routes", value: constraint.source_route_ids.join(" | ") || "none" },
      ],
    };
  }

  const route = scenario.station_routes.find((item) => item.id === selection.id);
  if (!route) return null;
  return {
    title: route.id,
    rows: [
      { label: "station", value: route.station_id },
      { label: "type", value: route.kind },
      { label: "boarding", value: route.allows_boarding ? "yes" : "no" },
      { label: "alighting", value: route.allows_alighting ? "yes" : "no" },
      { label: "segments", value: String(route.segment_ids.length) },
    ],
  };
}

function discreteSegmentRows(
  discreteScenario: DiscreteScenario,
  segmentId: string,
  discreteMode: DiscreteOverlayMode,
  discreteToggles: DiscreteViewerToggles,
) {
  const nodeIds = new Set<string>();
  const moveArcs = discreteScenario.arcs.filter((arc) => arc.kind === "move" && arc.source_segment_id === segmentId);
  for (const node of discreteScenario.nodes) {
    if (node.source_segment_id === segmentId) nodeIds.add(node.id);
  }
  for (const arc of moveArcs) {
    nodeIds.add(arc.from_node_id);
    nodeIds.add(arc.to_node_id);
  }

  const headwayConstraints = discreteScenario.constraints.filter(
    (constraint) =>
      constraint.kind === "headway" &&
      constraint.node_ids.some((nodeId) => nodeIds.has(nodeId)),
  );
  const ownSegmentHeadwayConstraints = headwayConstraints.filter(
    (constraint) => constraint.source_segment_ids.length === 1 && constraint.source_segment_ids[0] === segmentId,
  );
  const adjacentSegmentHeadwayConstraints = headwayConstraints.filter(
    (constraint) => constraint.source_segment_ids.length === 1 && constraint.source_segment_ids[0] !== segmentId,
  );
  const multiSegmentHeadwayConstraints = headwayConstraints.filter(
    (constraint) => constraint.source_segment_ids.length > 1,
  );
  const neighborSegments = new Set<string>();
  for (const constraint of [...adjacentSegmentHeadwayConstraints, ...multiSegmentHeadwayConstraints]) {
    for (const sourceSegmentId of constraint.source_segment_ids) {
      if (sourceSegmentId !== segmentId) neighborSegments.add(sourceSegmentId);
    }
  }

  const visibleConstraintCount =
    discreteMode === "neighborhood"
      ? (discreteToggles.showOwnSegmentHeadway ? ownSegmentHeadwayConstraints.length : 0) +
        (discreteToggles.showAdjacentSegmentHeadway ? adjacentSegmentHeadwayConstraints.length : 0) +
        (discreteToggles.showMultiSegmentHeadway ? multiSegmentHeadwayConstraints.length : 0)
      : 0;

  return [
    { label: "discrete nodes", value: String(nodeIds.size) },
    { label: "move arcs", value: String(moveArcs.length) },
    { label: "own segment", value: String(ownSegmentHeadwayConstraints.length), tone: "headway" },
    { label: "adjacent segment", value: String(adjacentSegmentHeadwayConstraints.length), tone: "headway" },
    { label: "multi-segment", value: String(multiSegmentHeadwayConstraints.length), tone: "headway" },
    { label: "visible constraints", value: String(visibleConstraintCount), tone: "headway" },
    { label: "neighbors", value: Array.from(neighborSegments).join(" | ") || "none" },
  ];
}

function speedProfileLabel(profile: SpeedProfile | null) {
  if (!profile) return "default";
  if (profile.kind === "constant") return `${profile.speed_m_per_s} m/s constant`;
  return `${profile.start_speed_m_per_s} -> ${profile.end_speed_m_per_s} m/s linear`;
}

function roundOne(value: number) {
  return Math.round(value * 10) / 10;
}
