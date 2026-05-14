import { Download, Maximize2, Move, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { CSSProperties, MouseEvent, PointerEvent } from "react";
import type { ScenarioLayout } from "../scenarioLayout";
import type { DiscreteScenario, Scenario, Selection, TrackSegment } from "../types";
import { SegmentSpeedGradient, segmentSpeedColor, segmentSpeedStroke, speedDomainForSegments, speedProfileLabel } from "./arcColor";
import { buildDiscreteOverlay, DiscreteOverlayLayer, physicalSelection } from "./DiscreteOverlayLayer";
import { useNodeLabelPlacements } from "./hooks/useNodeLabelPlacements";
import { LineViewLayer } from "./LineViewLayer";
import {
  clampViewBox,
  clientToViewBoxPoint,
  formatViewBox,
  parseViewBox,
  pointOnSegment,
  segmentArrowPlacement,
  segmentPath,
  zoomViewBox,
} from "./networkGeometry";
import type { NodeLabelPlacement, ReplayCabinMarker, ReplayCollisionMarker, ReplayStationQueueMarker, SegmentRouteInfo, SpeedDomain, ViewBoxState } from "./networkTypes";
import { ReplayCabinLayer, ReplayCollisionLayer, ReplayStationQueueLayer } from "./ReplayLayers";
import { screenNodeLabelPlacementMetrics } from "./scenarioFigureMetrics";
import { stationVisualColor } from "./stationColors";
import type { ArcColorMode, DiscreteOverlayMode, DiscreteViewerToggles, ScenarioDisplayMode, ViewerToggles } from "./viewerTypes";

export type { ReplayCabinMarker, ReplayCollisionMarker, ReplayStationQueueMarker } from "./networkTypes";

interface NetworkSvgProps {
  scenario: Scenario;
  discreteScenario: DiscreteScenario | null;
  layout: ScenarioLayout;
  selected: Selection | null;
  hovered: Selection | null;
  toggles: ViewerToggles;
  displayMode?: ScenarioDisplayMode;
  arcColorMode?: ArcColorMode;
  discreteMode: DiscreteOverlayMode;
  discreteToggles: DiscreteViewerToggles;
  replayCabins?: ReplayCabinMarker[];
  replayCollisionMarkers?: ReplayCollisionMarker[];
  replayStationQueues?: ReplayStationQueueMarker[];
  selectedCabinId?: number | null;
  onExportClick?: () => void;
  onSelect: (selection: Selection | null) => void;
  onHover: (selection: Selection | null) => void;
  onCabinSelect?: (cabinId: number) => void;
}

type PanState = {
  pointerId: number;
  startClientX: number;
  startClientY: number;
  startViewBox: ViewBoxState;
  hasMoved: boolean;
};

const NORMAL_MIN_VIEWBOX_SCALE = 0.25;
const DISCRETE_MIN_VIEWBOX_SCALE = 0.25;
export function NetworkSvg({
  scenario,
  discreteScenario,
  layout,
  selected,
  hovered,
  toggles,
  displayMode = "physical",
  arcColorMode = "type",
  discreteMode,
  discreteToggles,
  replayCabins = [],
  replayCollisionMarkers = [],
  replayStationQueues = [],
  selectedCabinId = null,
  onExportClick,
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
  const inverseZoom = 1 / zoom;
  const [labelPlacementScale, setLabelPlacementScale] = useState(inverseZoom);
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
  const isLineView = displayMode === "line";

  const visibleSegments = useMemo(
    () =>
      scenario.track_segments.filter((segment) => {
        const routeInfo = routeBySegment.get(segment.id);
        if (routeInfo?.routeKind === "service") return toggles.serviceRoutes;
        if (routeInfo?.routeKind === "skip") return toggles.skipRoutes;
        return true;
      }),
    [routeBySegment, scenario.track_segments, toggles.serviceRoutes, toggles.skipRoutes],
  );
  const speedDomain = useMemo(() => speedDomainForSegments(scenario.track_segments), [scenario.track_segments]);
  const nodeLabelInputKey = useMemo(
    () =>
      !isLineView && toggles.nodeLabels
        ? [
            layout.viewBox,
            scenario.physical_nodes.map((node) => node.id).join("|"),
            visibleSegments.map((segment) => segment.id).join("|"),
          ].join("::")
        : null,
    [isLineView, layout.viewBox, scenario.physical_nodes, toggles.nodeLabels, visibleSegments],
  );
  const nodeLabelMetrics = useMemo(() => screenNodeLabelPlacementMetrics(labelPlacementScale), [labelPlacementScale]);
  const nodeLabelPlacements = useNodeLabelPlacements({
    inputKey: nodeLabelInputKey,
    nodes: scenario.physical_nodes,
    visibleSegments,
    layout,
    viewBox: baseViewBox,
    metrics: nodeLabelMetrics,
  });

  const demandByStation = aggregateDemandByStation(scenario);
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
    setViewBox(baseViewBox);
  }, [baseViewBox, displayMode]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setLabelPlacementScale(inverseZoom);
    }, 140);
    return () => window.clearTimeout(timer);
  }, [inverseZoom]);

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

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const handleNativeWheel = (event: globalThis.WheelEvent) => {
      event.preventDefault();
      const rect = svg.getBoundingClientRect();
      const point = clientToViewBoxPoint(event.clientX, event.clientY, rect, viewBox);
      setViewBox((current) => zoomViewBox(current, baseViewBox, point, event.deltaY < 0 ? 0.88 : 1.12, minViewBoxScale));
    };
    svg.addEventListener("wheel", handleNativeWheel, { passive: false });
    return () => svg.removeEventListener("wheel", handleNativeWheel);
  }, [baseViewBox, minViewBoxScale, viewBox]);

  function resetView() {
    setViewBox(baseViewBox);
  }

  function zoomAtCenter(direction: "in" | "out") {
    const center = { x: viewBox.x + viewBox.width / 2, y: viewBox.y + viewBox.height / 2 };
    setViewBox((current) => zoomViewBox(current, baseViewBox, center, direction === "in" ? 0.82 : 1.18, minViewBoxScale));
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
        aria-label={isLineView ? "Schematic ropeway station line" : "Physical ropeway scenario network"}
        data-testid="network-svg"
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
          {arcColorMode === "speed"
            ? visibleSegments.map((segment) => <SegmentSpeedGradient key={`${segment.id}-speed-gradient`} segment={segment} layout={layout} speedDomain={speedDomain} />)
            : null}
        </defs>

        <rect x="-800" y="-520" width="2600" height="1600" fill={isLineView ? "#fbfcfb" : "url(#grid)"} onClick={() => onSelect(null)} />
        {isLineView ? (
          <LineViewLayer
            scenario={scenario}
            viewBox={baseViewBox}
            showLabels={toggles.nodeLabels}
            showDemand={toggles.demand}
            demandByStation={demandByStation}
            inverseZoom={inverseZoom}
          />
        ) : (
          <>
            {toggles.stationZones ? <StationZoneLayer scenario={scenario} layout={layout} inverseZoom={inverseZoom} /> : null}

            <g className="layer layer--infrastructure">
              {visibleSegments.map((segment) => (
                <SegmentPath
                  key={segment.id}
                  segment={segment}
                  routeInfo={routeBySegment.get(segment.id)}
                  layout={layout}
                  arcColorMode={arcColorMode}
                  speedDomain={speedDomain}
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
                  layout={layout}
                  arcColorMode={arcColorMode}
                  speedDomain={speedDomain}
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

            {toggles.arcLabels ? (
              <g className="layer layer--annotations">
                {visibleSegments.map((segment) => (
                  <SegmentLabel
                    key={`${segment.id}-label`}
                    segment={segment}
                    routeInfo={routeBySegment.get(segment.id)}
                    layout={layout}
                    arcColorMode={arcColorMode}
                    inverseZoom={inverseZoom}
                  />
                ))}
              </g>
            ) : null}

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
                  </g>
                );
              })}
            </g>

            {toggles.nodeLabels && nodeLabelInputKey !== null && nodeLabelPlacements.size > 0 ? (
              <g className="layer layer--node-labels">
                {scenario.physical_nodes.map((node) => {
                  const point = layout.nodes[node.id];
                  if (!point) return null;
                  const labelPlacement = nodeLabelPlacements.get(node.id) ?? { dx: 0, dy: -28 };
                  return (
                    <g key={`${node.id}-label`} className="node-label" transform={`translate(${point.x} ${point.y}) scale(${inverseZoom})`}>
                      <text x={labelPlacement.dx} y={labelPlacement.dy} textAnchor="middle" dominantBaseline="central">
                        {node.id.replaceAll("_", " ")}
                      </text>
                    </g>
                  );
                })}
              </g>
            ) : null}
          </>
        )}

        {toggles.demand && replayStationQueues.length > 0 ? (
          <ReplayStationQueueLayer queues={replayStationQueues} scenario={scenario} layout={layout} viewBox={viewBox} inverseZoom={inverseZoom} />
        ) : null}

        {replayCabins.length > 0 ? (
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
        {replayCollisionMarkers.length > 0 ? <ReplayCollisionLayer collisions={replayCollisionMarkers} inverseZoom={inverseZoom} /> : null}
      </svg>
      <div className="network-pan-hint">
        <Move size={14} />
        Drag to pan · wheel to zoom
      </div>
      {onExportClick ? (
        <button type="button" className="network-export-button" onClick={onExportClick}>
          <Download size={15} />
          Export
        </button>
      ) : null}
    </div>
  );
}

function shouldStartPan(target: EventTarget) {
  if (!(target instanceof Element)) return true;
  return !target.closest(".segment, .node, .discrete-node, .discrete-constraint, .replay-cabin");
}

function StationZoneLayer({ scenario, layout, inverseZoom }: { scenario: Scenario; layout: ScenarioLayout; inverseZoom: number }) {
  const filterId = `station-zone-blur-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const blurRadius = 12 * inverseZoom;

  return (
    <g className="layer layer--station-zones" aria-hidden="true">
      <defs>
        <filter id={filterId} x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation={blurRadius} />
        </filter>
      </defs>
      {scenario.stations.map((station) => {
        const bounds = stationBounds(station.id, scenario, layout);
        if (!bounds) return null;
        const paddingX = 34 * inverseZoom;
        const paddingY = 28 * inverseZoom;
        const color = stationVisualColor(station.id, scenario.stations);
        return (
          <rect
            key={station.id}
            className="station-zone"
            x={bounds.minX - paddingX}
            y={bounds.minY - paddingY}
            width={bounds.maxX - bounds.minX + paddingX * 2}
            height={bounds.maxY - bounds.minY + paddingY * 2}
            rx={18 * inverseZoom}
            filter={`url(#${filterId})`}
            style={{ "--station-zone-fill": color.haloFill, "--station-zone-stroke": color.haloStroke } as CSSProperties}
            vectorEffect="non-scaling-stroke"
          />
        );
      })}
    </g>
  );
}

function stationBounds(stationId: string, scenario: Scenario, layout: ScenarioLayout) {
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

function SegmentPath({
  segment,
  routeInfo,
  layout,
  arcColorMode,
  speedDomain,
  isSelected,
  isHovered,
  onSelect,
  onHover,
}: {
  segment: TrackSegment;
  routeInfo?: SegmentRouteInfo;
  layout: ScenarioLayout;
  arcColorMode: ArcColorMode;
  speedDomain: SpeedDomain;
  isSelected: boolean;
  isHovered: boolean;
  onSelect: (selection: Selection | null) => void;
  onHover: (selection: Selection | null) => void;
}) {
  const d = segmentPath(segment, layout);
  const routeKind = routeInfo?.routeKind ?? "rope";
  const speedStroke = arcColorMode === "speed" ? segmentSpeedStroke(segment, speedDomain) : undefined;
  return (
    <path
      className={`segment segment--${segment.kind} route--${routeKind} ${isSelected ? "is-selected" : ""} ${isHovered ? "is-hovered" : ""}`}
      d={d}
      style={speedStroke ? { stroke: speedStroke } : undefined}
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
  layout,
  arcColorMode,
  speedDomain,
  inverseZoom,
}: {
  segment: TrackSegment;
  layout: ScenarioLayout;
  arcColorMode: ArcColorMode;
  speedDomain: SpeedDomain;
  inverseZoom: number;
}) {
  const arrow = segmentArrowPlacement(segment, layout);
  if (!arrow) return null;
  const speedFill = arcColorMode === "speed" ? segmentSpeedColor(segment, speedDomain, arrow.t) : undefined;
  return (
    <g transform={`translate(${arrow.x} ${arrow.y}) rotate(${arrow.angleDeg}) scale(${inverseZoom})`}>
      <path className="segment-arrow__halo" d="M -13 -8 L 7 0 L -13 8 Z" />
      <path className={`segment-arrow segment-arrow--${segment.kind}`} d="M -11 -6 L 5 0 L -11 6 Z" style={speedFill ? { fill: speedFill } : undefined} />
    </g>
  );
}

function SegmentLabel({
  segment,
  routeInfo,
  layout,
  arcColorMode,
  inverseZoom,
}: {
  segment: TrackSegment;
  routeInfo?: SegmentRouteInfo;
  layout: ScenarioLayout;
  arcColorMode: ArcColorMode;
  inverseZoom: number;
}) {
  const midpoint = pointOnSegment(segment, layout, 0.5);
  if (!midpoint) return null;
  const typeLabel = routeInfo?.routeKind === "skip" ? "skip" : segment.kind;
  const label = arcColorMode === "speed" ? speedProfileLabel(segment.speed_profile) : typeLabel;
  const text = `${label} · ${segment.length_m}m`;
  const boxWidth = Math.max(76, text.length * 7.2 + 18);
  return (
    <g className={`segment-label segment-label--${routeInfo?.routeKind ?? segment.kind}`} transform={`translate(${midpoint.x} ${midpoint.y})`}>
      <g transform={`scale(${inverseZoom})`}>
        <rect x={-boxWidth / 2} y="-13" width={boxWidth} height="21" rx="4" />
        <text x="0" y="2">
          {text}
        </text>
      </g>
    </g>
  );
}

function aggregateDemandByStation(scenario: Scenario) {
  const totals = new Map<string, number>();
  for (const demand of scenario.demands) {
    totals.set(demand.origin, (totals.get(demand.origin) ?? 0) + demand.count);
  }
  return totals;
}
