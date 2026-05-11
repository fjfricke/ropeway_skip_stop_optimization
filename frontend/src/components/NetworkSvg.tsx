import { Maximize2, Move, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent, PointerEvent, WheelEvent } from "react";
import type { ScenarioLayout } from "../scenarioLayout";
import type { DiscreteArc, DiscreteConstraint, DiscreteNode, DiscreteScenario, Scenario, Selection, TrackSegment } from "../types";
import type { DiscreteOverlayMode, DiscreteViewerToggles, ViewerToggles } from "./ScenarioViewer";

export interface ReplayCabinMarker {
  cabinId: number;
  nodeId: string;
  incomingArcId?: string | null;
  loadCount?: number;
  capacity?: number;
  destinationLoads?: { destination: string; count: number }[];
}

export interface ReplayStationQueueMarker {
  stationId: string;
  totalCount: number;
  destinationQueues: { destination: string; count: number }[];
}

interface NetworkSvgProps {
  scenario: Scenario;
  discreteScenario: DiscreteScenario | null;
  layout: ScenarioLayout;
  selected: Selection | null;
  hovered: Selection | null;
  toggles: ViewerToggles;
  discreteMode: DiscreteOverlayMode;
  discreteToggles: DiscreteViewerToggles;
  replayCabins?: ReplayCabinMarker[];
  replayStationQueues?: ReplayStationQueueMarker[];
  selectedCabinId?: number | null;
  onSelect: (selection: Selection | null) => void;
  onHover: (selection: Selection | null) => void;
  onCabinSelect?: (cabinId: number) => void;
}

type SegmentRouteInfo = {
  routeId: string;
  routeKind: "service" | "skip";
};

type ViewBoxState = {
  x: number;
  y: number;
  width: number;
  height: number;
};

type PanState = {
  pointerId: number;
  startClientX: number;
  startClientY: number;
  startViewBox: ViewBoxState;
  hasMoved: boolean;
};

type DiscreteOverlayData = {
  nodes: DiscreteNode[];
  selectedNodeIds: Set<string>;
  arcs: DiscreteArc[];
  constraints: DiscreteConstraint[];
  haloSegmentIds: Set<string>;
};

const NORMAL_MIN_VIEWBOX_SCALE = 0.35;
const DISCRETE_MIN_VIEWBOX_SCALE = 0.2;
const MAX_VIEWBOX_SCALE = 1.8;

export function NetworkSvg({
  scenario,
  discreteScenario,
  layout,
  selected,
  hovered,
  toggles,
  discreteMode,
  discreteToggles,
  replayCabins = [],
  replayStationQueues = [],
  selectedCabinId = null,
  onSelect,
  onHover,
  onCabinSelect,
}: NetworkSvgProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const panRef = useRef<PanState | null>(null);
  const suppressClickRef = useRef(false);
  const baseViewBox = useMemo(() => parseViewBox(layout.viewBox), [layout.viewBox]);
  const [viewBox, setViewBox] = useState<ViewBoxState>(baseViewBox);
  const [isPanning, setIsPanning] = useState(false);

  const zoom = baseViewBox.width / viewBox.width;
  const routeBySegment = useMemo(() => {
    const routes = new Map<string, SegmentRouteInfo>();
    for (const route of scenario.station_routes) {
      for (const segmentId of route.segment_ids) {
        routes.set(segmentId, { routeId: route.id, routeKind: route.kind });
      }
    }
    return routes;
  }, [scenario.station_routes]);

  const segmentById = useMemo(() => new Map(scenario.track_segments.map((segment) => [segment.id, segment])), [scenario.track_segments]);

  const visibleSegments = scenario.track_segments.filter((segment) => {
    const routeInfo = routeBySegment.get(segment.id);
    if (routeInfo?.routeKind === "service") return toggles.serviceRoutes;
    if (routeInfo?.routeKind === "skip") return toggles.skipRoutes;
    return true;
  });

  const demandByStation = aggregateDemandByStation(scenario);
  const inverseZoom = 1 / zoom;
  const overlayAnchor = physicalSelection(selected);
  const discreteOverlay = useMemo(
    () =>
      buildDiscreteOverlay({
        discreteScenario,
        anchor: overlayAnchor,
        mode: discreteMode,
        toggles: discreteToggles,
      }),
    [discreteScenario, discreteMode, discreteToggles, overlayAnchor],
  );
  const minViewBoxScale = discreteOverlay ? DISCRETE_MIN_VIEWBOX_SCALE : NORMAL_MIN_VIEWBOX_SCALE;

  useEffect(() => {
    const minWidth = baseViewBox.width * minViewBoxScale;
    setViewBox((current) => {
      if (current.width >= minWidth) return current;
      const center = { x: current.x + current.width / 2, y: current.y + current.height / 2 };
      const targetHeight = minWidth * (baseViewBox.height / baseViewBox.width);
      return clampViewBox(
        {
          x: center.x - minWidth / 2,
          y: center.y - targetHeight / 2,
          width: minWidth,
          height: targetHeight,
        },
        baseViewBox,
      );
    });
  }, [baseViewBox, minViewBoxScale]);

  function resetView() {
    setViewBox(baseViewBox);
  }

  function zoomAtCenter(direction: "in" | "out") {
    const center = { x: viewBox.x + viewBox.width / 2, y: viewBox.y + viewBox.height / 2 };
    setViewBox((current) => zoomViewBox(current, baseViewBox, center, direction === "in" ? 0.82 : 1.18, minViewBoxScale));
  }

  function handleWheel(event: WheelEvent<SVGSVGElement>) {
    event.preventDefault();
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const point = clientToViewBoxPoint(event.clientX, event.clientY, rect, viewBox);
    setViewBox((current) => zoomViewBox(current, baseViewBox, point, event.deltaY < 0 ? 0.88 : 1.12, minViewBoxScale));
  }

  function handlePointerDown(event: PointerEvent<SVGSVGElement>) {
    if (event.button !== 0) return;
    if (!shouldStartPan(event.target)) return;
    panRef.current = {
      pointerId: event.pointerId,
      startClientX: event.clientX,
      startClientY: event.clientY,
      startViewBox: viewBox,
      hasMoved: false,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: PointerEvent<SVGSVGElement>) {
    const pan = panRef.current;
    const svg = svgRef.current;
    if (!pan || pan.pointerId !== event.pointerId || !svg) return;
    const rect = svg.getBoundingClientRect();
    const dx = event.clientX - pan.startClientX;
    const dy = event.clientY - pan.startClientY;
    if (!pan.hasMoved && Math.hypot(dx, dy) > 3) {
      pan.hasMoved = true;
      suppressClickRef.current = true;
      setIsPanning(true);
    }
    if (!pan.hasMoved) return;
    const next = {
      ...pan.startViewBox,
      x: pan.startViewBox.x - (dx / rect.width) * pan.startViewBox.width,
      y: pan.startViewBox.y - (dy / rect.height) * pan.startViewBox.height,
    };
    setViewBox(clampViewBox(next, baseViewBox));
  }

  function finishPan(event: PointerEvent<SVGSVGElement>) {
    const pan = panRef.current;
    if (!pan || pan.pointerId !== event.pointerId) return;
    panRef.current = null;
    setIsPanning(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function handleClickCapture(event: MouseEvent<SVGSVGElement>) {
    if (!suppressClickRef.current) return;
    event.stopPropagation();
    suppressClickRef.current = false;
  }

  return (
    <div className="network-svg-wrap">
      <div className="network-controls" aria-label="Network viewport controls">
        <button type="button" onClick={() => zoomAtCenter("out")} aria-label="Zoom out">
          <ZoomOut size={16} />
        </button>
        <span>{Math.round(zoom * 100)}%</span>
        <button type="button" onClick={() => zoomAtCenter("in")} aria-label="Zoom in">
          <ZoomIn size={16} />
        </button>
        <button type="button" onClick={resetView} aria-label="Reset view">
          <Maximize2 size={16} />
        </button>
      </div>
      <svg
        ref={svgRef}
        className={`network-svg ${isPanning ? "is-panning" : ""}`}
        viewBox={formatViewBox(viewBox)}
        role="img"
        aria-label="Physical ropeway scenario network"
        data-testid="network-svg"
        onWheel={handleWheel}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={finishPan}
        onPointerCancel={finishPan}
        onClickCapture={handleClickCapture}
      >
        <defs>
          <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="rgba(31, 42, 56, 0.06)" strokeWidth="1" />
          </pattern>
        </defs>

        <rect x="-800" y="-520" width="2600" height="1600" fill="url(#grid)" onClick={() => onSelect(null)} />
        <g className="layer layer--infrastructure">
          {visibleSegments.map((segment) => (
            <SegmentPath
              key={segment.id}
              segment={segment}
              routeInfo={routeBySegment.get(segment.id)}
              layout={layout}
              isSelected={selected?.type === "segment" && selected.id === segment.id}
              isHovered={hovered?.type === "segment" && hovered.id === segment.id}
              onSelect={onSelect}
              onHover={onHover}
            />
          ))}
          {discreteOverlay ? (
            <g className="layer layer--discrete-halo">
              {Array.from(discreteOverlay.haloSegmentIds).map((segmentId) => {
                const segment = segmentById.get(segmentId);
                if (!segment) return null;
                return <path key={segmentId} className="discrete-segment-halo" d={segmentPath(segment, layout)} vectorEffect="non-scaling-stroke" />;
              })}
            </g>
          ) : null}
          {visibleSegments.map((segment) => (
            <SegmentArrow
              key={`${segment.id}-arrow`}
              segment={segment}
              routeInfo={routeBySegment.get(segment.id)}
              layout={layout}
              inverseZoom={inverseZoom}
            />
          ))}
        </g>

        {discreteOverlay ? (
          <DiscreteOverlayLayer
            overlay={discreteOverlay}
            scenario={scenario}
            layout={layout}
            inverseZoom={inverseZoom}
            hovered={hovered}
            onHover={onHover}
          />
        ) : null}

        <g className="layer layer--annotations">
          {visibleSegments.map((segment) => (
            <SegmentLabel
              key={`${segment.id}-label`}
              segment={segment}
              routeInfo={routeBySegment.get(segment.id)}
              layout={layout}
              inverseZoom={inverseZoom}
            />
          ))}
        </g>

        <g className="layer layer--nodes">
          {scenario.physical_nodes.map((node) => {
            const point = layout.nodes[node.id];
            if (!point) return null;
            const selectedNode = selected?.type === "node" && selected.id === node.id;
            const hoveredNode = hovered?.type === "node" && hovered.id === node.id;
            return (
              <g
                key={node.id}
                className={`node node--${node.kind} ${selectedNode ? "is-selected" : ""} ${hoveredNode ? "is-hovered" : ""}`}
                transform={`translate(${point.x} ${point.y}) scale(${inverseZoom})`}
                onMouseEnter={() => onHover({ type: "node", id: node.id })}
                onMouseLeave={() => onHover(null)}
                onClick={(event) => {
                  event.stopPropagation();
                  onSelect(selectedNode ? null : { type: "node", id: node.id });
                }}
              >
                {node.kind.includes("switch") ? <path d="M0,-10 L12,10 L-12,10 Z" /> : <circle r={node.kind === "platform" ? 12 : 9} />}
                <text x={point.labelDx ?? 12} y={point.labelDy ?? -14}>
                  {node.id.replaceAll("_", " ")}
                </text>
              </g>
            );
          })}
        </g>

        {toggles.demand ? (
          <g className="layer layer--demand">
            {scenario.stations.map((station) => {
              const nodeId = station.id === "L" ? "L_platform_exit" : station.id === "R" ? "R_platform_exit" : "M_platform_entry_lr";
              const point = layout.nodes[nodeId];
              const count = demandByStation.get(station.id) ?? 0;
              if (!point || count === 0) return null;
              return (
                <g className="demand-badge" key={station.id} transform={`translate(${point.x + 18} ${point.y + 24}) scale(${inverseZoom})`}>
                  <rect x="0" y="0" width="54" height="25" rx="5" />
                  <text x="27" y="17">
                    {count} pax
                  </text>
                </g>
              );
            })}
          </g>
        ) : null}

        {replayStationQueues.length > 0 ? (
          <ReplayStationQueueLayer queues={replayStationQueues} layout={layout} inverseZoom={inverseZoom} />
        ) : null}

        {replayCabins.length > 0 && discreteScenario ? (
          <ReplayCabinLayer
            cabins={replayCabins}
            discreteScenario={discreteScenario}
            scenario={scenario}
            layout={layout}
            inverseZoom={inverseZoom}
            selectedCabinId={selectedCabinId}
            onCabinSelect={onCabinSelect}
          />
        ) : null}
      </svg>
      <div className="network-pan-hint">
        <Move size={14} />
        Drag to pan · wheel to zoom
      </div>
    </div>
  );
}

function shouldStartPan(target: EventTarget) {
  if (!(target instanceof Element)) return true;
  return !target.closest(".segment, .node, .discrete-node, .discrete-constraint, .replay-cabin");
}

function ReplayStationQueueLayer({
  queues,
  layout,
  inverseZoom,
}: {
  queues: ReplayStationQueueMarker[];
  layout: ScenarioLayout;
  inverseZoom: number;
}) {
  const maxQueue = Math.max(1, ...queues.map((queue) => queue.totalCount));
  return (
    <g className="layer layer--replay-queues">
      {queues.map((queue) => {
        const point = stationQueueAnchor(queue.stationId, layout);
        if (!point) return null;
        return (
          <g className="station-queue" key={queue.stationId} transform={`translate(${point.x} ${point.y}) scale(${inverseZoom})`}>
            <text className="station-queue__label" x="0" y="-8">
              {queue.totalCount} waiting
            </text>
            {queue.destinationQueues.map((item, index) => {
              const width = 18 + (item.count / maxQueue) * 54;
              return (
                <g key={item.destination} transform={`translate(0 ${index * 14})`}>
                  <rect className={`station-queue__bar station-queue__bar--${destinationClass(item.destination)}`} width={width} height="9" rx="2" />
                  <text x={width + 5} y="8">
                    {item.destination}:{item.count}
                  </text>
                </g>
              );
            })}
          </g>
        );
      })}
    </g>
  );
}

function ReplayCabinLayer({
  cabins,
  discreteScenario,
  scenario,
  layout,
  inverseZoom,
  selectedCabinId,
  onCabinSelect,
}: {
  cabins: ReplayCabinMarker[];
  discreteScenario: DiscreteScenario;
  scenario: Scenario;
  layout: ScenarioLayout;
  inverseZoom: number;
  selectedCabinId: number | null;
  onCabinSelect?: (cabinId: number) => void;
}) {
  const segmentById = new Map(scenario.track_segments.map((segment) => [segment.id, segment]));
  const nodeById = new Map(discreteScenario.nodes.map((node) => [node.id, node]));

  return (
    <g className="layer layer--replay-cabins">
      {cabins.map((cabin, index) => {
        const node = nodeById.get(cabin.nodeId);
        const point = node ? discreteNodePoint(node, layout, segmentById) : null;
        if (!point) return null;
        const selected = selectedCabinId === cabin.cabinId;
        const capacity = cabin.capacity ?? 0;
        const loadCount = cabin.loadCount ?? 0;
        const radius = selected ? 12 : 10;
        return (
          <g
            key={cabin.cabinId}
            className={`replay-cabin replay-cabin--${index % 6} ${loadCount > 0 ? "has-load" : ""} ${selected ? "is-selected" : ""}`}
            transform={`translate(${point.x} ${point.y}) scale(${inverseZoom})`}
            onClick={(event) => {
              event.stopPropagation();
              onCabinSelect?.(cabin.cabinId);
            }}
          >
            <circle className="replay-cabin__shell" r={radius} />
            <circle className="replay-cabin__empty" r={radius - 2.2} />
            {capacity > 0 ? (
              <g className="replay-cabin__pie">
                {cabinPieSlices(cabin.destinationLoads ?? [], capacity, radius - 2.2).map((slice) => (
                  <path key={slice.key} className={`replay-cabin__slice replay-cabin__slice--${destinationClass(slice.destination)}`} d={slice.d} />
                ))}
              </g>
            ) : null}
            <text x="0" y="3">
              C{cabin.cabinId}
            </text>
            <title>C{cabin.cabinId}: {loadCount}/{capacity || "?"} passengers · {cabin.nodeId}</title>
          </g>
        );
      })}
    </g>
  );
}

function cabinPieSlices(destinationLoads: { destination: string; count: number }[], capacity: number, radius: number) {
  if (capacity <= 0) return [];
  let cursor = -90;
  return destinationLoads.flatMap((item, index) => {
    if (item.count <= 0) return [];
    const sliceDegrees = Math.min(360, (item.count / capacity) * 360);
    const start = cursor;
    const end = cursor + sliceDegrees;
    cursor = end;
    return [{
      key: `${item.destination}-${index}`,
      destination: item.destination,
      d: sliceDegrees >= 359.999 ? fullCirclePath(radius) : pieSlicePath(radius, start, end),
    }];
  });
}

function pieSlicePath(radius: number, startDeg: number, endDeg: number) {
  const start = polarPoint(radius, startDeg);
  const end = polarPoint(radius, endDeg);
  const largeArc = endDeg - startDeg > 180 ? 1 : 0;
  return [
    "M 0 0",
    `L ${round(start.x)} ${round(start.y)}`,
    `A ${radius} ${radius} 0 ${largeArc} 1 ${round(end.x)} ${round(end.y)}`,
    "Z",
  ].join(" ");
}

function fullCirclePath(radius: number) {
  return [
    `M 0 ${-radius}`,
    `A ${radius} ${radius} 0 1 1 0 ${radius}`,
    `A ${radius} ${radius} 0 1 1 0 ${-radius}`,
    "Z",
  ].join(" ");
}

function polarPoint(radius: number, degrees: number) {
  const radians = (degrees * Math.PI) / 180;
  return {
    x: radius * Math.cos(radians),
    y: radius * Math.sin(radians),
  };
}

function destinationClass(destination: string) {
  return destination.toLowerCase().replace(/[^a-z0-9_-]/g, "");
}

function stationQueueAnchor(stationId: string, layout: ScenarioLayout) {
  if (stationId === "L") {
    const point = layout.nodes.L_platform_exit;
    return point ? { x: point.x + 24, y: point.y - 46 } : null;
  }
  if (stationId === "R") {
    const point = layout.nodes.R_platform_exit;
    return point ? { x: point.x - 112, y: point.y - 42 } : null;
  }
  if (stationId === "M") {
    const point = layout.nodes.M_platform_entry_lr;
    return point ? { x: point.x - 36, y: point.y - 64 } : null;
  }
  return null;
}

function DiscreteOverlayLayer({
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

function SegmentPath({
  segment,
  routeInfo,
  layout,
  isSelected,
  isHovered,
  onSelect,
  onHover,
}: {
  segment: TrackSegment;
  routeInfo?: SegmentRouteInfo;
  layout: ScenarioLayout;
  isSelected: boolean;
  isHovered: boolean;
  onSelect: (selection: Selection | null) => void;
  onHover: (selection: Selection | null) => void;
}) {
  const d = segmentPath(segment, layout);
  const routeKind = routeInfo?.routeKind ?? "rope";
  return (
    <path
      className={`segment segment--${segment.kind} route--${routeKind} ${isSelected ? "is-selected" : ""} ${isHovered ? "is-hovered" : ""}`}
      d={d}
      vectorEffect="non-scaling-stroke"
      onMouseEnter={() => onHover({ type: "segment", id: segment.id })}
      onMouseLeave={() => onHover(null)}
      onPointerDown={(event) => event.stopPropagation()}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(isSelected ? null : { type: "segment", id: segment.id });
      }}
    />
  );
}

function SegmentArrow({
  segment,
  routeInfo,
  layout,
  inverseZoom,
}: {
  segment: TrackSegment;
  routeInfo?: SegmentRouteInfo;
  layout: ScenarioLayout;
  inverseZoom: number;
}) {
  const arrow = segmentArrowPlacement(segment, layout);
  if (!arrow) return null;
  const routeKind = routeInfo?.routeKind ?? "rope";
  return (
    <g transform={`translate(${arrow.x} ${arrow.y}) rotate(${arrow.angleDeg}) scale(${inverseZoom})`}>
      <path className="segment-arrow__halo" d="M -13 -8 L 7 0 L -13 8 Z" />
      <path className={`segment-arrow segment-arrow--${routeKind}`} d="M -11 -6 L 5 0 L -11 6 Z" />
    </g>
  );
}

function SegmentLabel({
  segment,
  routeInfo,
  layout,
  inverseZoom,
}: {
  segment: TrackSegment;
  routeInfo?: SegmentRouteInfo;
  layout: ScenarioLayout;
  inverseZoom: number;
}) {
  const from = layout.nodes[segment.from_node_id];
  const to = layout.nodes[segment.to_node_id];
  if (!from || !to) return null;
  const hint = layout.segments[segment.id] ?? {};
  const x = (from.x + to.x) / 2 + (hint.labelDx ?? 0);
  const y = (from.y + to.y) / 2 + (hint.labelDy ?? -10);
  const label = routeInfo?.routeKind === "skip" ? "skip" : segment.kind;
  return (
    <g className={`segment-label segment-label--${routeInfo?.routeKind ?? segment.kind}`} transform={`translate(${x} ${y})`}>
      <g transform={`scale(${inverseZoom})`}>
        <rect x="-30" y="-13" width="60" height="21" rx="4" />
        <text x="0" y="2">
          {label} · {segment.length_m}m
        </text>
      </g>
    </g>
  );
}

function buildDiscreteOverlay({
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

function physicalSelection(selection: Selection | null): Selection | null {
  if (!selection) return null;
  return selection.type === "node" || selection.type === "segment" || selection.type === "route" ? selection : null;
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

function segmentPath(segment: TrackSegment, layout: ScenarioLayout) {
  const from = layout.nodes[segment.from_node_id];
  const to = layout.nodes[segment.to_node_id];
  if (!from || !to) return "";
  const curve = layout.segments[segment.id]?.curve ?? 0;
  if (curve === 0) return `M ${from.x} ${from.y} L ${to.x} ${to.y}`;
  const midX = (from.x + to.x) / 2;
  const midY = (from.y + to.y) / 2 + curve;
  return `M ${from.x} ${from.y} Q ${midX} ${midY} ${to.x} ${to.y}`;
}

function discreteNodePoint(
  node: DiscreteNode,
  layout: ScenarioLayout,
  segmentById: Map<string, TrackSegment>,
): { x: number; y: number } | null {
  if (node.source_physical_node_id) {
    return layout.nodes[node.source_physical_node_id] ?? null;
  }
  if (!node.source_segment_id || node.position_m === null) return null;
  const segment = segmentById.get(node.source_segment_id);
  if (!segment) return null;
  return pointOnSegment(segment, layout, node.position_m / segment.length_m);
}

function pointOnSegment(segment: TrackSegment, layout: ScenarioLayout, rawT: number) {
  const from = layout.nodes[segment.from_node_id];
  const to = layout.nodes[segment.to_node_id];
  const t = clamp(rawT, 0, 1);
  if (!from || !to) return null;
  const curve = layout.segments[segment.id]?.curve ?? 0;
  if (curve === 0) {
    return {
      x: from.x + (to.x - from.x) * t,
      y: from.y + (to.y - from.y) * t,
    };
  }

  const control = {
    x: (from.x + to.x) / 2,
    y: (from.y + to.y) / 2 + curve,
  };
  const oneMinusT = 1 - t;
  return {
    x: oneMinusT * oneMinusT * from.x + 2 * oneMinusT * t * control.x + t * t * to.x,
    y: oneMinusT * oneMinusT * from.y + 2 * oneMinusT * t * control.y + t * t * to.y,
  };
}

function segmentTangentAngle(segment: TrackSegment, layout: ScenarioLayout, rawT: number) {
  const from = layout.nodes[segment.from_node_id];
  const to = layout.nodes[segment.to_node_id];
  const t = clamp(rawT, 0, 1);
  if (!from || !to) return 0;
  const curve = layout.segments[segment.id]?.curve ?? 0;
  if (curve === 0) {
    return radiansToDegrees(Math.atan2(to.y - from.y, to.x - from.x));
  }

  const control = {
    x: (from.x + to.x) / 2,
    y: (from.y + to.y) / 2 + curve,
  };
  const oneMinusT = 1 - t;
  const dx = 2 * oneMinusT * (control.x - from.x) + 2 * t * (to.x - control.x);
  const dy = 2 * oneMinusT * (control.y - from.y) + 2 * t * (to.y - control.y);
  return radiansToDegrees(Math.atan2(dy, dx));
}

function waitArcPath(point: { x: number; y: number }, inverseZoom: number) {
  const radius = 9 * inverseZoom;
  return [
    `M ${round(point.x + radius)} ${round(point.y)}`,
    `C ${round(point.x + radius)} ${round(point.y - radius)}`,
    `${round(point.x - radius)} ${round(point.y - radius)}`,
    `${round(point.x - radius)} ${round(point.y)}`,
    `C ${round(point.x - radius)} ${round(point.y + radius)}`,
    `${round(point.x + radius)} ${round(point.y + radius)}`,
    `${round(point.x + radius)} ${round(point.y)}`,
  ].join(" ");
}

function segmentArrowPlacement(segment: TrackSegment, layout: ScenarioLayout) {
  const from = layout.nodes[segment.from_node_id];
  const to = layout.nodes[segment.to_node_id];
  if (!from || !to) return null;
  const curve = layout.segments[segment.id]?.curve ?? 0;
  const t = 0.7;
  if (curve === 0) {
    const x = from.x + (to.x - from.x) * t;
    const y = from.y + (to.y - from.y) * t;
    const angleDeg = radiansToDegrees(Math.atan2(to.y - from.y, to.x - from.x));
    return { x, y, angleDeg };
  }

  const control = {
    x: (from.x + to.x) / 2,
    y: (from.y + to.y) / 2 + curve,
  };
  const oneMinusT = 1 - t;
  const x = oneMinusT * oneMinusT * from.x + 2 * oneMinusT * t * control.x + t * t * to.x;
  const y = oneMinusT * oneMinusT * from.y + 2 * oneMinusT * t * control.y + t * t * to.y;
  const dx = 2 * oneMinusT * (control.x - from.x) + 2 * t * (to.x - control.x);
  const dy = 2 * oneMinusT * (control.y - from.y) + 2 * t * (to.y - control.y);
  return { x, y, angleDeg: radiansToDegrees(Math.atan2(dy, dx)) };
}

function radiansToDegrees(value: number) {
  return (value * 180) / Math.PI;
}

function aggregateDemandByStation(scenario: Scenario) {
  const totals = new Map<string, number>();
  for (const demand of scenario.demands) {
    totals.set(demand.origin, (totals.get(demand.origin) ?? 0) + demand.count);
  }
  return totals;
}

function parseViewBox(value: string): ViewBoxState {
  const [x, y, width, height] = value.split(/\s+/).map(Number);
  return { x, y, width, height };
}

function formatViewBox(value: ViewBoxState) {
  return `${round(value.x)} ${round(value.y)} ${round(value.width)} ${round(value.height)}`;
}

function round(value: number) {
  return Math.round(value * 1000) / 1000;
}

function clientToViewBoxPoint(clientX: number, clientY: number, rect: DOMRect, viewBox: ViewBoxState) {
  return {
    x: viewBox.x + ((clientX - rect.left) / rect.width) * viewBox.width,
    y: viewBox.y + ((clientY - rect.top) / rect.height) * viewBox.height,
  };
}

function zoomViewBox(
  current: ViewBoxState,
  base: ViewBoxState,
  center: { x: number; y: number },
  scaleFactor: number,
  minViewBoxScale: number,
) {
  const targetWidth = clamp(current.width * scaleFactor, base.width * minViewBoxScale, base.width * MAX_VIEWBOX_SCALE);
  const targetHeight = targetWidth * (base.height / base.width);
  const ratioX = (center.x - current.x) / current.width;
  const ratioY = (center.y - current.y) / current.height;
  return clampViewBox(
    {
      x: center.x - targetWidth * ratioX,
      y: center.y - targetHeight * ratioY,
      width: targetWidth,
      height: targetHeight,
    },
    base,
  );
}

function clampViewBox(value: ViewBoxState, base: ViewBoxState) {
  const marginX = base.width * 0.45;
  const marginY = base.height * 0.45;
  return {
    ...value,
    x: clamp(value.x, base.x - marginX, base.x + base.width + marginX - value.width),
    y: clamp(value.y, base.y - marginY, base.y + base.height + marginY - value.height),
  };
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}
