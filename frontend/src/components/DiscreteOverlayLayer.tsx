import type { ScenarioLayout } from "../scenarioLayout";
import type { DiscreteArc, DiscreteConstraint, DiscreteNode, DiscreteScenario, Scenario, Selection, TrackSegment } from "../types";
import type { DiscreteOverlayMode, DiscreteViewerToggles } from "./viewerTypes";
import { discreteNodePoint, pointOnSegment, segmentPath, segmentTangentAngle, waitArcPath } from "./networkGeometry";
import type { DiscreteOverlayData } from "./networkTypes";

export function DiscreteOverlayLayer({
  overlay,
  scenario,
  layout,
  inverseZoom,
  hovered,
  onHover,
}: {
  overlay: DiscreteOverlayData;
  scenario: Scenario;
  layout: ScenarioLayout;
  inverseZoom: number;
  hovered: Selection | null;
  onHover: (selection: Selection | null) => void;
}) {
  const segmentById = new Map(scenario.track_segments.map((segment) => [segment.id, segment]));
  const nodeById = new Map(overlay.nodes.map((node) => [node.id, node]));
  const moveArcsBySegmentId = groupMoveArcsBySegment(overlay.arcs);
  const waitArcs = overlay.arcs.filter((arc) => arc.kind === "wait");
  const moveChevrons = Array.from(moveArcsBySegmentId).flatMap(([segmentId, arcs]) => {
    const segment = segmentById.get(segmentId);
    if (!segment) return [];
    return discreteMoveChevrons(arcs, segment, nodeById, layout);
  });

  return (
    <g className="layer layer--discrete">
      <g className="layer--discrete-constraints">
        {overlay.constraints.map((constraint) => {
          const points = constraint.node_ids
            .map((nodeId) => nodeById.get(nodeId))
            .map((node) => (node ? discreteNodePoint(node, layout, segmentById) : null));
          if (!points[0] || !points[1]) return null;
          const hoveredConstraint = hovered?.type === "discrete_constraint" && hovered.id === constraint.id;
          return (
            <line
              key={constraint.id}
              className={`discrete-constraint discrete-constraint--${constraint.scope} ${hoveredConstraint ? "is-hovered" : ""}`}
              x1={points[0].x}
              y1={points[0].y}
              x2={points[1].x}
              y2={points[1].y}
              vectorEffect="non-scaling-stroke"
              onMouseEnter={() => onHover({ type: "discrete_constraint", id: constraint.id })}
              onMouseLeave={() => onHover(null)}
            >
              <title>{constraint.scope} headway: {constraint.node_ids.join(" | ")}</title>
            </line>
          );
        })}
      </g>

      <g className="layer--discrete-arcs">
        {Array.from(moveArcsBySegmentId).map(([segmentId]) => {
          const segment = segmentById.get(segmentId);
          if (!segment) return null;
          return <path key={`${segmentId}-move-band`} className="discrete-move-band" d={segmentPath(segment, layout)} vectorEffect="non-scaling-stroke" />;
        })}

        {waitArcs.map((arc) => {
          const fromNode = nodeById.get(arc.from_node_id);
          const from = fromNode ? discreteNodePoint(fromNode, layout, segmentById) : null;
          if (!from) return null;
          const hoveredArc = hovered?.type === "discrete_arc" && hovered.id === arc.id;
          return (
            <path
              key={arc.id}
              className={`discrete-arc discrete-arc--wait ${hoveredArc ? "is-hovered" : ""}`}
              d={waitArcPath(from, inverseZoom)}
              vectorEffect="non-scaling-stroke"
              onMouseEnter={() => onHover({ type: "discrete_arc", id: arc.id })}
              onMouseLeave={() => onHover(null)}
            >
              <title>{arc.kind}: {arc.id}</title>
            </path>
          );
        })}
      </g>

      <g className="layer--discrete-nodes">
        {overlay.nodes.map((node) => {
          const point = discreteNodePoint(node, layout, segmentById);
          if (!point) return null;
          const selectedNode = overlay.selectedNodeIds.has(node.id);
          const hoveredNode = hovered?.type === "discrete_node" && hovered.id === node.id;
          return (
            <g
              key={node.id}
              className={`discrete-node ${selectedNode ? "discrete-node--selected" : "discrete-node--neighbor"} ${
                node.allows_waiting ? "discrete-node--waiting" : ""
              } ${hoveredNode ? "is-hovered" : ""}`}
              transform={`translate(${point.x} ${point.y}) scale(${inverseZoom})`}
              onMouseEnter={() => onHover({ type: "discrete_node", id: node.id })}
              onMouseLeave={() => onHover(null)}
            >
              {node.allows_waiting ? <rect x="-5" y="-5" width="10" height="10" rx="2" /> : <circle r={4.5} />}
              <title>{node.id}</title>
            </g>
          );
        })}
      </g>

      <g className="layer--discrete-direction">
        {moveChevrons.map((chevron) => (
          <g
            key={chevron.id}
            className="discrete-move-chevron"
            transform={`translate(${chevron.x} ${chevron.y}) rotate(${chevron.angleDeg}) scale(${inverseZoom})`}
          >
            <path className="discrete-move-chevron__halo" d="M -7 -7 L 6 0 L -7 7" />
            <path d="M -7 -7 L 6 0 L -7 7" />
          </g>
        ))}
      </g>
    </g>
  );
}

export function buildDiscreteOverlay({
  discreteScenario,
  anchor,
  mode,
  toggles,
}: {
  discreteScenario: DiscreteScenario | null;
  anchor: Selection | null;
  mode: DiscreteOverlayMode;
  toggles: DiscreteViewerToggles;
}): DiscreteOverlayData | null {
  if (!discreteScenario || !toggles.enabled || !anchor) return null;

  const nodeById = new Map(discreteScenario.nodes.map((node) => [node.id, node]));
  const arcById = new Map(discreteScenario.arcs.map((arc) => [arc.id, arc]));
  const selectedNodeIds = new Set<string>();
  const selectedArcIds = new Set<string>();
  const haloSegmentIds = new Set<string>();

  if (anchor.type === "segment") {
    haloSegmentIds.add(anchor.id);
    for (const node of discreteScenario.nodes) {
      if (node.source_segment_id === anchor.id) {
        selectedNodeIds.add(node.id);
      }
    }
    for (const arc of discreteScenario.arcs) {
      if (arc.source_segment_id === anchor.id) {
        selectedArcIds.add(arc.id);
        selectedNodeIds.add(arc.from_node_id);
        selectedNodeIds.add(arc.to_node_id);
      }
    }
  }

  if (anchor.type === "node") {
    const nodeId = `pn::${anchor.id}`;
    selectedNodeIds.add(nodeId);
    for (const arc of discreteScenario.arcs) {
      if (arc.from_node_id === nodeId || arc.to_node_id === nodeId) {
        selectedArcIds.add(arc.id);
      }
    }
  }

  if (anchor.type === "route") {
    const route = discreteScenario.routes.find((item) => item.source_route_id === anchor.id || item.id === anchor.id);
    for (const arcId of route?.arc_ids ?? []) {
      const arc = arcById.get(arcId);
      if (!arc) continue;
      selectedArcIds.add(arc.id);
      selectedNodeIds.add(arc.from_node_id);
      selectedNodeIds.add(arc.to_node_id);
      if (arc.source_segment_id) haloSegmentIds.add(arc.source_segment_id);
    }
  }

  if (selectedNodeIds.size === 0 && selectedArcIds.size === 0) return null;

  const visibleNodeIds = new Set(selectedNodeIds);
  const visibleConstraintIds = new Set<string>();

  if (mode === "neighborhood") {
    for (const constraint of discreteScenario.constraints) {
      if (!constraintPassesToggles(constraint, toggles, anchor)) continue;
      if (!constraint.node_ids.some((nodeId) => selectedNodeIds.has(nodeId))) continue;
      visibleConstraintIds.add(constraint.id);
      for (const nodeId of constraint.node_ids) visibleNodeIds.add(nodeId);
      for (const segmentId of constraint.source_segment_ids) haloSegmentIds.add(segmentId);
    }
  }

  for (const nodeId of visibleNodeIds) {
    const node = nodeById.get(nodeId);
    if (node?.source_segment_id) haloSegmentIds.add(node.source_segment_id);
  }

  const visibleArcIds = new Set<string>();
  for (const arc of discreteScenario.arcs) {
    if (arc.kind === "move" && !toggles.showMoveArcs) continue;
    if (arc.kind === "wait" && !toggles.showWaitArcs) continue;

    const isSelectedArc = selectedArcIds.has(arc.id);
    if (mode === "selected" && isSelectedArc) {
      visibleArcIds.add(arc.id);
    }
    if (mode === "neighborhood" && isSelectedArc) {
      visibleArcIds.add(arc.id);
      visibleNodeIds.add(arc.from_node_id);
      visibleNodeIds.add(arc.to_node_id);
      if (arc.source_segment_id) haloSegmentIds.add(arc.source_segment_id);
    }
  }

  const constraints = discreteScenario.constraints.filter((constraint) => visibleConstraintIds.has(constraint.id));
  const arcs = discreteScenario.arcs.filter((arc) => visibleArcIds.has(arc.id));
  const nodes = Array.from(visibleNodeIds)
    .map((nodeId) => nodeById.get(nodeId))
    .filter((node): node is DiscreteNode => Boolean(node));

  return { nodes, selectedNodeIds, arcs, constraints, haloSegmentIds };
}

export function physicalSelection(selection: Selection | null): Selection | null {
  if (!selection) return null;
  return selection.type === "node" || selection.type === "segment" || selection.type === "route" ? selection : null;
}

function constraintPassesToggles(constraint: DiscreteConstraint, toggles: DiscreteViewerToggles, anchor: Selection) {
  if (constraint.kind !== "headway") return false;
  if (anchor.type !== "segment") {
    if (constraint.scope === "same_segment") return toggles.showOwnSegmentHeadway || toggles.showAdjacentSegmentHeadway;
    if (constraint.scope === "cross_segment") return toggles.showMultiSegmentHeadway;
    return false;
  }
  if (constraint.source_segment_ids.length === 1 && constraint.source_segment_ids[0] === anchor.id) {
    return toggles.showOwnSegmentHeadway;
  }
  if (constraint.source_segment_ids.length === 1) {
    return toggles.showAdjacentSegmentHeadway;
  }
  return toggles.showMultiSegmentHeadway;
}

function groupMoveArcsBySegment(arcs: DiscreteArc[]) {
  const arcsBySegmentId = new Map<string, DiscreteArc[]>();
  for (const arc of arcs) {
    if (arc.kind !== "move" || !arc.source_segment_id) continue;
    arcsBySegmentId.set(arc.source_segment_id, [...(arcsBySegmentId.get(arc.source_segment_id) ?? []), arc]);
  }
  for (const segmentArcs of arcsBySegmentId.values()) {
    segmentArcs.sort((left, right) => discreteArcStep(left) - discreteArcStep(right));
  }
  return arcsBySegmentId;
}

function discreteMoveChevrons(
  arcs: DiscreteArc[],
  segment: TrackSegment,
  nodeById: Map<string, DiscreteNode>,
  layout: ScenarioLayout,
) {
  const maxChevrons = segment.kind === "rope" ? 14 : 7;
  const stride = Math.max(1, Math.ceil(arcs.length / maxChevrons));
  return arcs.flatMap((arc, index) => {
    if (index % stride !== 0) return [];
    const t = arcMidpointT(arc, segment, nodeById);
    if (t === null) return [];
    if (arcs.length > 4 && (t < 0.08 || t > 0.92)) return [];
    const point = pointOnSegment(segment, layout, t);
    if (!point) return [];
    return [
      {
        id: arc.id,
        x: point.x,
        y: point.y,
        angleDeg: segmentTangentAngle(segment, layout, t),
      },
    ];
  });
}

function discreteArcStep(arc: DiscreteArc) {
  return Number(arc.id.split("::").at(-1)) || 0;
}

function arcMidpointT(arc: DiscreteArc, segment: TrackSegment, nodeById: Map<string, DiscreteNode>) {
  const from = nodeTOnSegment(nodeById.get(arc.from_node_id), segment);
  const to = nodeTOnSegment(nodeById.get(arc.to_node_id), segment);
  if (from === null || to === null) return null;
  return (from + to) / 2;
}

function nodeTOnSegment(node: DiscreteNode | undefined, segment: TrackSegment) {
  if (!node) return null;
  if (node.source_segment_id === segment.id && node.position_m !== null) {
    return node.position_m / segment.length_m;
  }
  if (node.source_physical_node_id === segment.from_node_id) return 0;
  if (node.source_physical_node_id === segment.to_node_id) return 1;
  return null;
}
