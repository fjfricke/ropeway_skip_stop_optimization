import { Maximize2, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent, PointerEvent } from "react";
import type { ScenarioLayout } from "../scenarioLayout";
import type { Scenario, TrackSegment } from "../types";
import { SegmentSpeedGradient, segmentSpeedColor, segmentSpeedStroke, speedDomainForSegments, speedProfileLabel } from "./arcColor";
import { lineArcId, lineViewPoints, stationLabel } from "./LineViewLayer";
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
import { aggregateDemandByStation, isSegmentEnabled, routeInfoBySegment } from "./scenarioExportGeometry";
import { screenNodeLabelPlacementMetrics } from "./scenarioFigureMetrics";
import type { ScenarioExportConfig } from "./viewerTypes";

interface ScenarioExportSelectorSvgProps {
  scenario: Scenario;
  layout: ScenarioLayout;
  config: ScenarioExportConfig;
  selectedNodeIds: Set<string>;
  selectedArcIds: Set<string>;
  replayCabins?: ReplayCabinMarker[];
  replayCollisionMarkers?: ReplayCollisionMarker[];
  replayStationQueues?: ReplayStationQueueMarker[];
  showCabinFill?: boolean;
  onNodeToggle: (id: string) => void;
  onArcToggle: (id: string) => void;
}

type PanState = {
  pointerId: number;
  startClientX: number;
  startClientY: number;
  startViewBox: ViewBoxState;
  hasMoved: boolean;
};

const SELECTOR_MIN_VIEWBOX_SCALE = 0.25;
const EMPTY_NODE_LABEL_PLACEMENTS = new Map<string, NodeLabelPlacement>();

type NodeLabelPlacementWorkerResponse = {
  jobId: number;
  placements: [string, NodeLabelPlacement][];
};

export function ScenarioExportSelectorSvg({
  scenario,
  layout,
  config,
  selectedNodeIds,
  selectedArcIds,
  replayCabins = [],
  replayCollisionMarkers = [],
  replayStationQueues = [],
  showCabinFill = true,
  onNodeToggle,
  onArcToggle,
}: ScenarioExportSelectorSvgProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const panRef = useRef<PanState | null>(null);
  const suppressClickRef = useRef(false);
  const baseViewBox = useMemo(() => parseViewBox(layout.viewBox), [layout.viewBox]);
  const [viewBox, setViewBox] = useState<ViewBoxState>(baseViewBox);
  const [isPanning, setIsPanning] = useState(false);
  const zoom = baseViewBox.width / viewBox.width;
  const inverseZoom = 1 / zoom;
  const [labelPlacementScale, setLabelPlacementScale] = useState(inverseZoom);
  const labelPlacementWorkerRef = useRef<Worker | null>(null);
  const labelPlacementJobIdRef = useRef(0);
  const lastNodeLabelInputKeyRef = useRef<string | null>(null);
  const [nodeLabelState, setNodeLabelState] = useState<{
    inputKey: string | null;
    placements: Map<string, NodeLabelPlacement>;
  }>({
    inputKey: null,
    placements: EMPTY_NODE_LABEL_PLACEMENTS,
  });
  const speedDomain = useMemo(() => speedDomainForSegments(scenario.track_segments), [scenario.track_segments]);
  const routeBySegment = useMemo(() => routeInfoBySegment(scenario), [scenario]);
  const visibleSegments = useMemo(
    () => scenario.track_segments.filter((segment) => isSegmentEnabled(segment, routeBySegment.get(segment.id), config)),
    [config, routeBySegment, scenario.track_segments],
  );
  const demandByStation = useMemo(() => aggregateDemandByStation(scenario), [scenario]);
  const nodeLabelInputKey = useMemo(
    () =>
      config.displayMode === "physical" && config.toggles.nodeLabels
        ? [
            layout.viewBox,
            scenario.physical_nodes.map((node) => node.id).join("|"),
            visibleSegments.map((segment) => segment.id).join("|"),
          ].join("::")
        : null,
    [config.displayMode, config.toggles.nodeLabels, layout.viewBox, scenario.physical_nodes, visibleSegments],
  );
  const shouldRenderNodeLabels = nodeLabelInputKey !== null && nodeLabelState.inputKey === nodeLabelInputKey;
  const nodeLabelPlacements = shouldRenderNodeLabels ? nodeLabelState.placements : EMPTY_NODE_LABEL_PLACEMENTS;

  useEffect(() => {
    setViewBox(baseViewBox);
  }, [baseViewBox, config.displayMode]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setLabelPlacementScale(inverseZoom);
    }, 140);
    return () => window.clearTimeout(timer);
  }, [inverseZoom]);

  useEffect(() => {
    labelPlacementWorkerRef.current?.terminate();
    labelPlacementWorkerRef.current = null;
    labelPlacementJobIdRef.current += 1;

    if (nodeLabelInputKey === null) {
      lastNodeLabelInputKeyRef.current = null;
      setNodeLabelState({ inputKey: null, placements: EMPTY_NODE_LABEL_PLACEMENTS });
      return undefined;
    }

    const inputChanged = lastNodeLabelInputKeyRef.current !== nodeLabelInputKey;
    lastNodeLabelInputKeyRef.current = nodeLabelInputKey;
    if (inputChanged) {
      setNodeLabelState({ inputKey: null, placements: EMPTY_NODE_LABEL_PLACEMENTS });
    }

    const jobId = labelPlacementJobIdRef.current;
    const frame = window.requestAnimationFrame(() => {
      const worker = new Worker(new URL("./nodeLabelPlacement.worker.ts", import.meta.url), { type: "module" });
      labelPlacementWorkerRef.current = worker;
      worker.onmessage = (event: MessageEvent<NodeLabelPlacementWorkerResponse>) => {
        if (event.data.jobId !== labelPlacementJobIdRef.current) return;
        setNodeLabelState({
          inputKey: nodeLabelInputKey,
          placements: new Map(event.data.placements),
        });
        worker.terminate();
        if (labelPlacementWorkerRef.current === worker) {
          labelPlacementWorkerRef.current = null;
        }
      };
      worker.postMessage({
        jobId,
        nodes: scenario.physical_nodes,
        visibleSegments,
        layout,
        viewBox: baseViewBox,
        metrics: screenNodeLabelPlacementMetrics(labelPlacementScale),
      });
    });

    return () => {
      window.cancelAnimationFrame(frame);
      labelPlacementWorkerRef.current?.terminate();
      labelPlacementWorkerRef.current = null;
    };
  }, [baseViewBox, labelPlacementScale, layout, nodeLabelInputKey, scenario.physical_nodes, visibleSegments]);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return undefined;
    const handleNativeWheel = (event: globalThis.WheelEvent) => {
      event.preventDefault();
      const rect = svg.getBoundingClientRect();
      const point = clientToViewBoxPoint(event.clientX, event.clientY, rect, viewBox);
      setViewBox((current) => zoomViewBox(current, baseViewBox, point, event.deltaY < 0 ? 0.88 : 1.12, SELECTOR_MIN_VIEWBOX_SCALE));
    };
    svg.addEventListener("wheel", handleNativeWheel, { passive: false });
    return () => svg.removeEventListener("wheel", handleNativeWheel);
  }, [baseViewBox, viewBox]);

  function resetView() {
    setViewBox(baseViewBox);
  }

  function zoomAtCenter(direction: "in" | "out") {
    const center = { x: viewBox.x + viewBox.width / 2, y: viewBox.y + viewBox.height / 2 };
    setViewBox((current) => zoomViewBox(current, baseViewBox, center, direction === "in" ? 0.82 : 1.18, SELECTOR_MIN_VIEWBOX_SCALE));
  }

  function handlePointerDown(event: PointerEvent<SVGSVGElement>) {
    if (event.button !== 0) return;
    if (!shouldStartSelectorPan(event.target)) return;
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
    <div className="scenario-selector-wrap">
      <div className="network-controls" aria-label="Selector viewport controls">
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
        className={`scenario-selector-svg ${isPanning ? "is-panning" : ""}`}
        viewBox={formatViewBox(viewBox)}
        role="img"
        aria-label={config.displayMode === "line" ? "Scenario line export selector" : "Scenario physical export selector"}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={finishPan}
        onPointerCancel={finishPan}
        onClickCapture={handleClickCapture}
      >
        <defs>
          {config.displayMode === "physical" && config.arcColorMode === "speed"
            ? visibleSegments.map((segment) => <SegmentSpeedGradient key={`${segment.id}-selector-speed-gradient`} segment={segment} layout={layout} speedDomain={speedDomain} />)
            : null}
        </defs>
        <rect
          className="scenario-selector__background"
          x={baseViewBox.x - baseViewBox.width}
          y={baseViewBox.y - baseViewBox.height}
          width={baseViewBox.width * 3}
          height={baseViewBox.height * 3}
        />
        {config.displayMode === "line" ? (
          <SelectorLineLayer
            scenario={scenario}
            viewBox={baseViewBox}
            selectedNodeIds={selectedNodeIds}
            selectedArcIds={selectedArcIds}
            showLabels={config.toggles.nodeLabels}
            showDemand={config.toggles.demand}
            demandByStation={demandByStation}
            inverseZoom={inverseZoom}
            onNodeToggle={onNodeToggle}
            onArcToggle={onArcToggle}
          />
        ) : (
          <SelectorPhysicalLayer
            scenario={scenario}
            layout={layout}
            segments={visibleSegments}
            routeBySegment={routeBySegment}
            selectedNodeIds={selectedNodeIds}
            selectedArcIds={selectedArcIds}
            arcColorMode={config.arcColorMode}
            speedDomain={speedDomain}
            showNodeLabels={config.toggles.nodeLabels}
            showArcLabels={config.toggles.arcLabels}
            nodeLabelPlacements={nodeLabelPlacements}
            inverseZoom={inverseZoom}
            onNodeToggle={onNodeToggle}
            onArcToggle={onArcToggle}
          />
        )}
        {config.displayMode === "physical" && config.toggles.demand && replayStationQueues.length > 0 ? (
          <ReplayStationQueueLayer queues={replayStationQueues} scenario={scenario} layout={layout} viewBox={viewBox} inverseZoom={inverseZoom} />
        ) : null}
        {config.displayMode === "physical" && replayCabins.length > 0 ? (
          <ReplayCabinLayer
            cabins={replayCabins}
            discreteScenario={null}
            scenario={scenario}
            layout={layout}
            inverseZoom={inverseZoom}
            selectedCabinId={null}
            showFill={showCabinFill}
          />
        ) : null}
        {config.displayMode === "physical" && replayCollisionMarkers.length > 0 ? (
          <ReplayCollisionLayer collisions={replayCollisionMarkers} inverseZoom={inverseZoom} />
        ) : null}
      </svg>
    </div>
  );
}

function shouldStartSelectorPan(target: EventTarget) {
  if (!(target instanceof Element)) return true;
  return !target.closest(".scenario-selector__node, .scenario-selector__arc, .scenario-selector__line-hit-arc, .scenario-selector__hit-arc");
}

function SelectorLineLayer({
  scenario,
  viewBox,
  selectedNodeIds,
  selectedArcIds,
  showLabels,
  showDemand,
  demandByStation,
  inverseZoom,
  onNodeToggle,
  onArcToggle,
}: {
  scenario: Scenario;
  viewBox: { x: number; y: number; width: number; height: number };
  selectedNodeIds: Set<string>;
  selectedArcIds: Set<string>;
  showLabels: boolean;
  showDemand: boolean;
  demandByStation: Map<string, number>;
  inverseZoom: number;
  onNodeToggle: (id: string) => void;
  onArcToggle: (id: string) => void;
}) {
  const points = lineViewPoints(scenario, viewBox);
  return (
    <g className="line-view scenario-selector-line" aria-label="Schematic station line selector">
      {points.slice(0, -1).map((point, index) => {
        const next = points[index + 1];
        const id = lineArcId(point.station.id, next.station.id);
        const path = `M ${point.x} ${point.y} L ${next.x} ${next.y}`;
        const selected = selectedArcIds.has(id);
        const hitX = Math.min(point.x, next.x);
        const hitY = Math.min(point.y, next.y) - 14 * inverseZoom;
        const hitWidth = Math.max(1, Math.abs(next.x - point.x));
        return (
          <g key={id} className={selected ? "" : "is-export-muted"} onClick={() => onArcToggle(id)}>
            <path className="line-view__track-halo" d={path} />
            <path className="line-view__track scenario-selector__arc" d={path} />
            <rect className="scenario-selector__line-hit-arc" x={hitX} y={hitY} width={hitWidth} height={28 * inverseZoom} />
          </g>
        );
      })}
      {points.map(({ station, x, y }) => {
        const selected = selectedNodeIds.has(station.id);
        const radius = station.kind === "terminal" ? 12 : 10;
        const labelOffset = radius + 14;
        const demandOffset = radius + 14 + 12;
        const demandCount = demandByStation.get(station.id) ?? 0;
        return (
          <g
            key={station.id}
            className={`line-view-station line-view-station--${station.kind} scenario-selector__node ${selected ? "" : "is-export-muted"}`}
            transform={`translate(${x} ${y}) scale(${inverseZoom})`}
            onClick={() => onNodeToggle(station.id)}
          >
            <circle r={radius} />
            {showLabels ? (
              <text x="0" y={-labelOffset}>
                {stationLabel(station)}
              </text>
            ) : null}
            {showDemand && demandCount > 0 ? (
              <g className="line-view-demand" transform={`translate(0 ${demandOffset})`}>
                <rect x="-27" y="-12" width="54" height="24" rx="5" />
                <text x="0" y="4">
                  {demandCount} pax
                </text>
              </g>
            ) : null}
          </g>
        );
      })}
    </g>
  );
}

function SelectorPhysicalLayer({
  scenario,
  layout,
  segments,
  routeBySegment,
  selectedNodeIds,
  selectedArcIds,
  arcColorMode,
  speedDomain,
  showNodeLabels,
  showArcLabels,
  nodeLabelPlacements,
  inverseZoom,
  onNodeToggle,
  onArcToggle,
}: {
  scenario: Scenario;
  layout: ScenarioLayout;
  segments: TrackSegment[];
  routeBySegment: Map<string, SegmentRouteInfo>;
  selectedNodeIds: Set<string>;
  selectedArcIds: Set<string>;
  arcColorMode: "type" | "speed";
  speedDomain: SpeedDomain;
  showNodeLabels: boolean;
  showArcLabels: boolean;
  nodeLabelPlacements: Map<string, NodeLabelPlacement>;
  inverseZoom: number;
  onNodeToggle: (id: string) => void;
  onArcToggle: (id: string) => void;
}) {
  return (
    <>
      <g className="layer layer--infrastructure">
        {segments.map((segment) => (
          <SelectorSegment
            key={segment.id}
            segment={segment}
            routeInfo={routeBySegment.get(segment.id)}
            layout={layout}
            selected={selectedArcIds.has(segment.id)}
            arcColorMode={arcColorMode}
            speedDomain={speedDomain}
            onToggle={onArcToggle}
          />
        ))}
        {segments.map((segment) => (
          <SelectorSegmentArrow
            key={`${segment.id}-arrow`}
            segment={segment}
            layout={layout}
            selected={selectedArcIds.has(segment.id)}
            arcColorMode={arcColorMode}
            speedDomain={speedDomain}
            inverseZoom={inverseZoom}
          />
        ))}
      </g>

      {showArcLabels ? (
        <g className="layer layer--annotations">
          {segments.map((segment) => (
            <SelectorSegmentLabel
              key={`${segment.id}-selector-label`}
              segment={segment}
              routeInfo={routeBySegment.get(segment.id)}
              layout={layout}
              arcColorMode={arcColorMode}
              selected={selectedArcIds.has(segment.id)}
              inverseZoom={inverseZoom}
            />
          ))}
        </g>
      ) : null}

      <g className="layer layer--nodes">
        {scenario.physical_nodes.map((node) => {
          const point = layout.nodes[node.id];
          if (!point) return null;
          const selected = selectedNodeIds.has(node.id);
          return (
            <g
              key={node.id}
              className={`node node--${node.kind} scenario-selector__node ${selected ? "" : "is-export-muted"}`}
              transform={`translate(${point.x} ${point.y}) scale(${inverseZoom})`}
              onClick={() => onNodeToggle(node.id)}
            >
              {node.kind.includes("switch") ? <path d="M0,-10 L12,10 L-12,10 Z" /> : <circle r={node.kind === "platform" ? 12 : 9} />}
            </g>
          );
        })}
      </g>

      {showNodeLabels ? (
        <g className="layer layer--node-labels">
          {scenario.physical_nodes.map((node) => {
            const point = layout.nodes[node.id];
            if (!point) return null;
            const labelPlacement = nodeLabelPlacements.get(node.id) ?? { dx: 0, dy: -28 };
            return (
              <g
                key={`${node.id}-selector-node-label`}
                className={`node-label ${selectedNodeIds.has(node.id) ? "" : "is-export-muted"}`}
                transform={`translate(${point.x} ${point.y}) scale(${inverseZoom})`}
              >
                <text x={labelPlacement.dx} y={labelPlacement.dy} textAnchor="middle" dominantBaseline="central">
                  {node.id.replaceAll("_", " ")}
                </text>
              </g>
            );
          })}
        </g>
      ) : null}
    </>
  );
}

function SelectorSegment({
  segment,
  routeInfo,
  layout,
  selected,
  arcColorMode,
  speedDomain,
  onToggle,
}: {
  segment: TrackSegment;
  routeInfo?: SegmentRouteInfo;
  layout: ScenarioLayout;
  selected: boolean;
  arcColorMode: "type" | "speed";
  speedDomain: SpeedDomain;
  onToggle: (id: string) => void;
}) {
  const d = segmentPath(segment, layout);
  const speedStroke = selected && arcColorMode === "speed" ? segmentSpeedStroke(segment, speedDomain) : undefined;
  return (
    <g className={selected ? "" : "is-export-muted"} onClick={() => onToggle(segment.id)}>
      <path
        className={`segment segment--${segment.kind} route--${routeInfo?.routeKind ?? "rope"} scenario-selector__arc`}
        d={d}
        style={speedStroke ? { stroke: speedStroke } : undefined}
        vectorEffect="non-scaling-stroke"
      />
      <path className="scenario-selector__hit-arc" d={d} />
    </g>
  );
}

function SelectorSegmentLabel({
  segment,
  routeInfo,
  layout,
  arcColorMode,
  selected,
  inverseZoom,
}: {
  segment: TrackSegment;
  routeInfo?: SegmentRouteInfo;
  layout: ScenarioLayout;
  arcColorMode: "type" | "speed";
  selected: boolean;
  inverseZoom: number;
}) {
  const midpoint = pointOnSegment(segment, layout, 0.5);
  if (!midpoint) return null;
  const typeLabel = routeInfo?.routeKind === "skip" ? "skip" : segment.kind;
  const label = arcColorMode === "speed" ? speedProfileLabel(segment.speed_profile) : typeLabel;
  const text = `${label} · ${segment.length_m}m`;
  const boxWidth = Math.max(76, text.length * 7.2 + 18);
  return (
    <g className={`segment-label ${selected ? "" : "is-export-muted"}`} transform={`translate(${midpoint.x} ${midpoint.y})`}>
      <g transform={`scale(${inverseZoom})`}>
        <rect x={-boxWidth / 2} y="-13" width={boxWidth} height="21" rx="4" />
        <text x="0" y="2">
          {text}
        </text>
      </g>
    </g>
  );
}

function SelectorSegmentArrow({
  segment,
  layout,
  selected,
  arcColorMode,
  speedDomain,
  inverseZoom,
}: {
  segment: TrackSegment;
  layout: ScenarioLayout;
  selected: boolean;
  arcColorMode: "type" | "speed";
  speedDomain: SpeedDomain;
  inverseZoom: number;
}) {
  const arrow = segmentArrowPlacement(segment, layout);
  if (!arrow) return null;
  const speedFill = selected && arcColorMode === "speed" ? segmentSpeedColor(segment, speedDomain, arrow.t) : undefined;
  return (
    <g className={selected ? "" : "is-export-muted"} transform={`translate(${arrow.x} ${arrow.y}) rotate(${arrow.angleDeg}) scale(${inverseZoom})`}>
      <path className="segment-arrow__halo" d="M -13 -8 L 7 0 L -13 8 Z" />
      <path className={`segment-arrow segment-arrow--${segment.kind}`} d="M -11 -6 L 5 0 L -11 6 Z" style={speedFill ? { fill: speedFill } : undefined} />
    </g>
  );
}
