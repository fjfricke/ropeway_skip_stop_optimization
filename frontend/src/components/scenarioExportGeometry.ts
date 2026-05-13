import type { ScenarioLayout } from "../scenarioLayout";
import type { Scenario, Station, TrackSegment } from "../types";
import { speedProfileLabel } from "./arcColor";
import { lineArcId, lineViewPoints, lineViewStations, stationLabel } from "./LineViewLayer";
import { buildNodeLabelPlacements, estimateNodeLabelSize } from "./nodeLabelPlacement";
import { pointOnSegment, round, segmentPath } from "./networkGeometry";
import type { NodeLabelPlacement, SegmentRouteInfo, ViewBoxState } from "./networkTypes";
import {
  A4_PORTRAIT_300_DPI,
  estimateTextSize,
  exportVisualMetrics,
  REPORT_TEXT_WIDTH_300_DPI,
  type ScenarioExportVisualMetrics,
} from "./scenarioFigureMetrics";
import type { ScenarioExportConfig } from "./export/exportTypes";

export type ExportArcRenderMode = "full" | "from_start" | "from_end";

export type ExportSegmentRender = {
  segment: TrackSegment;
  routeInfo?: SegmentRouteInfo;
  mode: ExportArcRenderMode;
  canRenderLabel: boolean;
};

export type ExportLineLinkRender = {
  id: string;
  fromStationId: string;
  toStationId: string;
  from: { x: number; y: number };
  to: { x: number; y: number };
  mode: ExportArcRenderMode;
};

export type ScenarioExportRenderPlan = {
  viewBox: ViewBoxState;
  outputWidth: number;
  outputHeight: number;
  metrics: ScenarioExportVisualMetrics;
  physicalNodeLabelPlacements: Map<string, NodeLabelPlacement>;
  physicalNodes: Set<string>;
  physicalSegments: ExportSegmentRender[];
  lineStations: Set<string>;
  lineLinks: ExportLineLinkRender[];
};

type Bounds = {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
};

type PrimitiveRenderPlan = {
  bounds: Bounds;
  physicalNodes: Set<string>;
  physicalSegments: ExportSegmentRender[];
  lineStations: Set<string>;
  lineLinks: ExportLineLinkRender[];
};

const EMPTY_BOUNDS: Bounds = {
  minX: Number.POSITIVE_INFINITY,
  minY: Number.POSITIVE_INFINITY,
  maxX: Number.NEGATIVE_INFINITY,
  maxY: Number.NEGATIVE_INFINITY,
};

export function buildScenarioExportRenderPlan({
  scenario,
  layout,
  config,
}: {
  scenario: Scenario;
  layout: ScenarioLayout;
  config: ScenarioExportConfig;
}): ScenarioExportRenderPlan {
  const baseViewBox = parseLayoutViewBox(layout.viewBox);
  const routeBySegment = routeInfoBySegment(scenario);
  const visibleSegments = scenario.track_segments.filter((segment) => isSegmentEnabled(segment, routeBySegment.get(segment.id), config));
  const renderPlan =
    config.displayMode === "line"
      ? buildLineRenderPlan(scenario, baseViewBox, config)
      : buildPhysicalRenderPlan(scenario, layout, visibleSegments, routeBySegment, config);

  let viewBox = fitBoundsToAspect(padBounds(renderPlan.bounds, 1), targetAspectFromConfig(renderPlan.bounds));
  let output = outputDimensions(config, viewBox);
  let metrics = exportVisualMetrics(viewBox, output.width, baseViewBox);
  let physicalNodeLabelPlacements = buildPhysicalNodeLabelPlacements(scenario, layout, config, renderPlan, viewBox, metrics);

  for (let pass = 0; pass < 3; pass += 1) {
    const visualBounds = visualBoundsForRenderPlan({
      scenario,
      layout,
      config,
      renderPlan,
      baseViewBox,
      metrics,
      physicalNodeLabelPlacements,
    });
    viewBox = fitBoundsToAspect(padBounds(visualBounds, metrics.boundsPadding), targetAspectFromConfig(visualBounds));
    output = outputDimensions(config, viewBox);
    metrics = exportVisualMetrics(viewBox, output.width, baseViewBox);
    physicalNodeLabelPlacements = buildPhysicalNodeLabelPlacements(scenario, layout, config, renderPlan, viewBox, metrics);
  }

  return {
    viewBox,
    outputWidth: output.width,
    outputHeight: output.height,
    metrics,
    physicalNodeLabelPlacements,
    physicalNodes: renderPlan.physicalNodes,
    physicalSegments: renderPlan.physicalSegments,
    lineStations: renderPlan.lineStations,
    lineLinks: renderPlan.lineLinks,
  };
}

export function routeInfoBySegment(scenario: Scenario) {
  const routeBySegment = new Map<string, SegmentRouteInfo>();
  for (const route of scenario.station_routes) {
    for (const segmentId of route.segment_ids) {
      routeBySegment.set(segmentId, { routeId: route.id, routeKind: route.kind });
    }
  }
  return routeBySegment;
}

export function isSegmentEnabled(segment: TrackSegment, routeInfo: SegmentRouteInfo | undefined, config: ScenarioExportConfig) {
  if (routeInfo?.routeKind === "service") return config.toggles.serviceRoutes;
  if (routeInfo?.routeKind === "skip") return config.toggles.skipRoutes;
  return segment.kind !== "skip" || config.toggles.skipRoutes;
}

export function exportSegmentPath(segment: TrackSegment, layout: ScenarioLayout, mode: ExportArcRenderMode) {
  if (mode === "full") return segmentPath(segment, layout);
  return mode === "from_start" ? segmentPathRange(segment, layout, 0, 0.5) : segmentPathRange(segment, layout, 0.5, 1);
}

export function exportSegmentArrowPlacement(segment: TrackSegment, layout: ScenarioLayout, mode: ExportArcRenderMode) {
  const t = mode === "full" ? 0.7 : mode === "from_start" ? 0.35 : 0.65;
  const point = pointOnSegment(segment, layout, t);
  const tangent = segmentTangentAt(segment, layout, t);
  if (!point || !tangent) return null;
  return { x: point.x, y: point.y, angleDeg: tangent, t };
}

export function aggregateDemandByStation(scenario: Scenario) {
  const totals = new Map<string, number>();
  for (const demand of scenario.demands) {
    totals.set(demand.origin, (totals.get(demand.origin) ?? 0) + demand.count);
  }
  return totals;
}

function buildPhysicalNodeLabelPlacements(
  scenario: Scenario,
  layout: ScenarioLayout,
  config: ScenarioExportConfig,
  renderPlan: PrimitiveRenderPlan,
  viewBox: ViewBoxState,
  metrics: ScenarioExportVisualMetrics,
) {
  if (config.displayMode === "line" || !config.toggles.nodeLabels) return new Map<string, NodeLabelPlacement>();
  const nodes = scenario.physical_nodes.filter((node) => renderPlan.physicalNodes.has(node.id));
  return buildNodeLabelPlacements({
    nodes,
    visibleSegments: renderPlan.physicalSegments.map((segmentRender) => segmentRender.segment),
    layout,
    viewBox,
    metrics: metrics.nodeLabelPlacement,
  });
}

function visualBoundsForRenderPlan({
  scenario,
  layout,
  config,
  renderPlan,
  baseViewBox,
  metrics,
  physicalNodeLabelPlacements,
}: {
  scenario: Scenario;
  layout: ScenarioLayout;
  config: ScenarioExportConfig;
  renderPlan: PrimitiveRenderPlan;
  baseViewBox: ViewBoxState;
  metrics: ScenarioExportVisualMetrics;
  physicalNodeLabelPlacements: Map<string, NodeLabelPlacement>;
}) {
  const bounds = copyBounds(renderPlan.bounds);
  if (config.displayMode === "line") {
    includeLineVisualBounds(bounds, scenario, baseViewBox, renderPlan, config, metrics);
  } else {
    includePhysicalVisualBounds(bounds, scenario, layout, renderPlan, config, metrics, physicalNodeLabelPlacements);
  }
  return bounds;
}

function includeLineVisualBounds(
  bounds: Bounds,
  scenario: Scenario,
  baseViewBox: ViewBoxState,
  renderPlan: PrimitiveRenderPlan,
  config: ScenarioExportConfig,
  metrics: ScenarioExportVisualMetrics,
) {
  const demandByStation = aggregateDemandByStation(scenario);
  const points = lineViewPoints(scenario, baseViewBox);
  const pointByStation = new Map(points.map((point) => [point.station.id, point]));
  for (const link of renderPlan.lineLinks) {
    includeLineLinkBounds(bounds, link, metrics.lineTrackHaloWidth / 2);
  }
  for (const station of lineViewStations(scenario)) {
    if (!renderPlan.lineStations.has(station.id)) continue;
    const point = pointByStation.get(station.id);
    if (!point) continue;
    const radius = lineStationRadius(station, metrics);
    includeCircle(bounds, point, radius + metrics.nodeStrokeWidth);
    if (config.toggles.nodeLabels) {
      const textSize = estimateTextSize(stationLabel(station), {
        fontSize: metrics.stationLabelFontSize,
        charWidthFactor: metrics.textCharWidthFactor,
        lineHeightFactor: metrics.lineHeightFactor,
      });
      const centerY = point.y - radius - metrics.lineStationLabelGap - textSize.height / 2;
      includeRect(bounds, {
        x: point.x - textSize.width / 2,
        y: centerY - textSize.height / 2,
        width: textSize.width,
        height: textSize.height,
      });
    }
    const demandCount = demandByStation.get(station.id) ?? 0;
    if (config.toggles.demand && demandCount > 0) {
      includeDemandBox(bounds, `${demandCount} pax`, point.x, point.y + radius + metrics.lineDemandGap + metrics.demandBoxHeight / 2, metrics);
    }
  }
}

function includePhysicalVisualBounds(
  bounds: Bounds,
  scenario: Scenario,
  layout: ScenarioLayout,
  renderPlan: PrimitiveRenderPlan,
  config: ScenarioExportConfig,
  metrics: ScenarioExportVisualMetrics,
  physicalNodeLabelPlacements: Map<string, NodeLabelPlacement>,
) {
  for (const segmentRender of renderPlan.physicalSegments) {
    includeSegmentBounds(bounds, segmentRender.segment, layout, segmentRender.mode);
    const arrow = exportSegmentArrowPlacement(segmentRender.segment, layout, segmentRender.mode);
    if (arrow) {
      includeRect(bounds, {
        x: arrow.x - 13 * metrics.arrowScale,
        y: arrow.y - 9 * metrics.arrowScale,
        width: 26 * metrics.arrowScale,
        height: 18 * metrics.arrowScale,
      });
    }
    if (config.toggles.arcLabels && segmentRender.canRenderLabel) {
      const midpoint = pointOnSegment(segmentRender.segment, layout, 0.5);
      if (midpoint) {
        const textSize = arcLabelTextSize(segmentRender, config, metrics);
        includeRect(bounds, {
          x: midpoint.x - textSize.width / 2,
          y: midpoint.y - metrics.arcLabelHeight / 2,
          width: textSize.width,
          height: metrics.arcLabelHeight,
        });
      }
    }
  }
  for (const node of scenario.physical_nodes) {
    if (!renderPlan.physicalNodes.has(node.id)) continue;
    const point = layout.nodes[node.id];
    if (!point) continue;
    const radius = node.kind === "platform" ? metrics.platformNodeRadius : metrics.physicalNodeRadius;
    includeCircle(bounds, point, radius + metrics.nodeStrokeWidth);
    if (config.toggles.nodeLabels) {
      const placement = physicalNodeLabelPlacements.get(node.id) ?? { dx: 0, dy: -28 * (metrics.nodeLabelFontSize / 12) };
      const textSize = estimateNodeLabelSize(node.id.replaceAll("_", " "), metrics.nodeLabelPlacement);
      includeRect(bounds, {
        x: point.x + placement.dx - textSize.width / 2,
        y: point.y + placement.dy - textSize.height / 2,
        width: textSize.width,
        height: textSize.height,
      });
    }
  }
  const strokePadding = Math.max(metrics.segmentStrokeWidth, metrics.lineTrackHaloWidth, metrics.nodeStrokeWidth) / 2;
  expandBoundsInPlace(bounds, strokePadding);
}

function buildLineRenderPlan(scenario: Scenario, baseViewBox: ViewBoxState, config: ScenarioExportConfig) {
  const points = lineViewPoints(scenario, baseViewBox);
  const selectedNodes = new Set(config.selectedNodeIds);
  const selectedArcs = new Set(config.selectedArcIds);
  const exportedStations = new Set<string>();
  const links: ExportLineLinkRender[] = [];
  const bounds = { ...EMPTY_BOUNDS };

  for (const point of points) {
    if (selectedNodes.has(point.station.id)) {
      exportedStations.add(point.station.id);
      includePoint(bounds, point);
    }
  }

  for (let index = 0; index < points.length - 1; index += 1) {
    const from = points[index];
    const to = points[index + 1];
    const id = lineArcId(from.station.id, to.station.id);
    if (!selectedArcs.has(id)) continue;
    const fromSelected = exportedStations.has(from.station.id);
    const toSelected = exportedStations.has(to.station.id);
    if (!fromSelected && !toSelected) continue;
    const mode: ExportArcRenderMode = fromSelected && toSelected ? "full" : fromSelected ? "from_start" : "from_end";
    const midpoint = midpointOf(from, to);
    links.push({
      id,
      fromStationId: from.station.id,
      toStationId: to.station.id,
      from,
      to,
      mode,
    });
    includePoint(bounds, mode === "from_end" ? midpoint : from);
    includePoint(bounds, mode === "from_start" ? midpoint : to);
  }

  if (!hasBounds(bounds)) {
    for (const point of points) includePoint(bounds, point);
  }

  return {
    bounds,
    physicalNodes: new Set<string>(),
    physicalSegments: [],
    lineStations: exportedStations,
    lineLinks: links,
  };
}

function buildPhysicalRenderPlan(
  scenario: Scenario,
  layout: ScenarioLayout,
  visibleSegments: TrackSegment[],
  routeBySegment: Map<string, SegmentRouteInfo>,
  config: ScenarioExportConfig,
) {
  const selectedNodes = new Set(config.selectedNodeIds);
  const selectedArcs = new Set(config.selectedArcIds);
  const physicalNodes = new Set<string>();
  const physicalSegments: ExportSegmentRender[] = [];
  const bounds = { ...EMPTY_BOUNDS };

  for (const node of scenario.physical_nodes) {
    if (!layout.nodes[node.id]) continue;
    if (selectedNodes.has(node.id)) {
      physicalNodes.add(node.id);
      includePoint(bounds, layout.nodes[node.id]);
    }
  }

  for (const segment of visibleSegments) {
    if (!selectedArcs.has(segment.id)) continue;
    const fromIncluded = physicalNodes.has(segment.from_node_id);
    const toIncluded = physicalNodes.has(segment.to_node_id);
    if (!fromIncluded && !toIncluded) continue;
    const mode: ExportArcRenderMode = fromIncluded && toIncluded ? "full" : fromIncluded ? "from_start" : "from_end";
    physicalSegments.push({
      segment,
      routeInfo: routeBySegment.get(segment.id),
      mode,
      canRenderLabel: mode === "full",
    });
    includeSegmentBounds(bounds, segment, layout, mode);
  }

  if (!hasBounds(bounds)) {
    const base = parseLayoutViewBox(layout.viewBox);
    includePoint(bounds, { x: base.x, y: base.y });
    includePoint(bounds, { x: base.x + base.width, y: base.y + base.height });
  }

  return {
    bounds,
    physicalNodes,
    physicalSegments,
    lineStations: new Set<string>(),
    lineLinks: [],
  };
}

function lineStationRadius(station: Station, metrics: ScenarioExportVisualMetrics) {
  return station.kind === "terminal" ? metrics.terminalStationRadius : metrics.stationRadius;
}

function includeLineLinkBounds(bounds: Bounds, link: ExportLineLinkRender, padding: number) {
  const midpoint = midpointOf(link.from, link.to);
  const from = link.mode === "from_end" ? midpoint : link.from;
  const to = link.mode === "from_start" ? midpoint : link.to;
  includePoint(bounds, from);
  includePoint(bounds, to);
  includeRect(bounds, {
    x: Math.min(from.x, to.x) - padding,
    y: Math.min(from.y, to.y) - padding,
    width: Math.abs(to.x - from.x) + padding * 2,
    height: Math.abs(to.y - from.y) + padding * 2,
  });
}

function arcLabelTextSize(segmentRender: ExportSegmentRender, config: ScenarioExportConfig, metrics: ScenarioExportVisualMetrics) {
  const typeLabel = segmentRender.routeInfo?.routeKind === "skip" ? "skip" : segmentRender.segment.kind;
  const label = config.arcColorMode === "speed" ? speedProfileLabel(segmentRender.segment.speed_profile) : typeLabel;
  const text = `${label} · ${segmentRender.segment.length_m}m`;
  const textSize = estimateTextSize(text, {
    fontSize: metrics.arcLabelFontSize,
    charWidthFactor: metrics.textCharWidthFactor,
    lineHeightFactor: metrics.lineHeightFactor,
  });
  return {
    width: Math.max(76 * metrics.arrowScale, textSize.width + metrics.arcLabelPaddingX * 2),
    height: metrics.arcLabelHeight,
  };
}

function includeDemandBox(bounds: Bounds, text: string, centerX: number, centerY: number, metrics: ScenarioExportVisualMetrics) {
  const textSize = estimateTextSize(text, {
    fontSize: metrics.demandFontSize,
    charWidthFactor: metrics.textCharWidthFactor,
    lineHeightFactor: metrics.lineHeightFactor,
  });
  const width = Math.max(metrics.demandBoxHeight * 2.25, textSize.width + metrics.demandBoxPaddingX * 2);
  includeRect(bounds, {
    x: centerX - width / 2,
    y: centerY - metrics.demandBoxHeight / 2,
    width,
    height: metrics.demandBoxHeight,
  });
}

function parseLayoutViewBox(value: string): ViewBoxState {
  const [x, y, width, height] = value.split(/\s+/).map(Number);
  return { x, y, width, height };
}

function outputDimensions(config: ScenarioExportConfig, viewBox: ViewBoxState) {
  const percentage = Math.max(1, Math.min(400, config.percentage));
  const basisPx = config.basis === "a4_height"
    ? A4_PORTRAIT_300_DPI.height
    : config.basis === "text_width"
      ? REPORT_TEXT_WIDTH_300_DPI
      : A4_PORTRAIT_300_DPI.width;
  const fixed = Math.round((basisPx * percentage) / 100);
  if (config.basis === "a4_width" || config.basis === "text_width") {
    return {
      width: fixed,
      height: Math.max(1, Math.round(fixed * (viewBox.height / viewBox.width))),
    };
  }
  return {
    width: Math.max(1, Math.round(fixed * (viewBox.width / viewBox.height))),
    height: fixed,
  };
}

function targetAspectFromConfig(bounds: Bounds) {
  const naturalWidth = Math.max(1, bounds.maxX - bounds.minX);
  const naturalHeight = Math.max(1, bounds.maxY - bounds.minY);
  return naturalWidth / naturalHeight;
}

function fitBoundsToAspect(bounds: Bounds, aspect: number): ViewBoxState {
  const width = Math.max(1, bounds.maxX - bounds.minX);
  const height = Math.max(1, bounds.maxY - bounds.minY);
  const currentAspect = width / height;
  if (currentAspect < aspect) {
    const nextWidth = height * aspect;
    const delta = nextWidth - width;
    return {
      x: round(bounds.minX - delta / 2),
      y: round(bounds.minY),
      width: round(nextWidth),
      height: round(height),
    };
  }
  const nextHeight = width / aspect;
  const delta = nextHeight - height;
  return {
    x: round(bounds.minX),
    y: round(bounds.minY - delta / 2),
    width: round(width),
    height: round(nextHeight),
  };
}

function padBounds(bounds: Bounds, padding: number): Bounds {
  if (!hasBounds(bounds)) return { minX: 0, minY: 0, maxX: 1, maxY: 1 };
  return {
    minX: bounds.minX - padding,
    minY: bounds.minY - padding,
    maxX: bounds.maxX + padding,
    maxY: bounds.maxY + padding,
  };
}

function includeSegmentBounds(bounds: Bounds, segment: TrackSegment, layout: ScenarioLayout, mode: ExportArcRenderMode) {
  const fromT = mode === "from_end" ? 0.5 : 0;
  const toT = mode === "from_start" ? 0.5 : 1;
  for (let i = 0; i <= 12; i += 1) {
    const t = fromT + ((toT - fromT) * i) / 12;
    const point = pointOnSegment(segment, layout, t);
    if (point) includePoint(bounds, point);
  }
}

function segmentPathRange(segment: TrackSegment, layout: ScenarioLayout, startT: number, endT: number) {
  const from = layout.nodes[segment.from_node_id];
  const to = layout.nodes[segment.to_node_id];
  if (!from || !to) return "";
  const start = pointOnSegment(segment, layout, startT);
  const end = pointOnSegment(segment, layout, endT);
  if (!start || !end) return "";
  const curve = layout.segments[segment.id]?.curve ?? 0;
  if (curve === 0) return `M ${round(start.x)} ${round(start.y)} L ${round(end.x)} ${round(end.y)}`;

  const control = {
    x: (from.x + to.x) / 2,
    y: (from.y + to.y) / 2 + curve,
  };
  const [left, right] = splitQuadratic(from, control, to, startT);
  const remainingT = startT === 1 ? 1 : (endT - startT) / (1 - startT);
  const [part] = splitQuadratic(left[2], right[1], right[2], remainingT);
  return `M ${round(part[0].x)} ${round(part[0].y)} Q ${round(part[1].x)} ${round(part[1].y)} ${round(part[2].x)} ${round(part[2].y)}`;
}

function splitQuadratic(
  p0: { x: number; y: number },
  p1: { x: number; y: number },
  p2: { x: number; y: number },
  t: number,
) {
  const p01 = interpolatePoint(p0, p1, t);
  const p12 = interpolatePoint(p1, p2, t);
  const p012 = interpolatePoint(p01, p12, t);
  return [
    [p0, p01, p012],
    [p012, p12, p2],
  ] as const;
}

function segmentTangentAt(segment: TrackSegment, layout: ScenarioLayout, t: number) {
  const from = layout.nodes[segment.from_node_id];
  const to = layout.nodes[segment.to_node_id];
  if (!from || !to) return null;
  const curve = layout.segments[segment.id]?.curve ?? 0;
  if (curve === 0) return radiansToDegrees(Math.atan2(to.y - from.y, to.x - from.x));
  const control = {
    x: (from.x + to.x) / 2,
    y: (from.y + to.y) / 2 + curve,
  };
  const dx = 2 * (1 - t) * (control.x - from.x) + 2 * t * (to.x - control.x);
  const dy = 2 * (1 - t) * (control.y - from.y) + 2 * t * (to.y - control.y);
  return radiansToDegrees(Math.atan2(dy, dx));
}

function midpointOf(left: { x: number; y: number }, right: { x: number; y: number }) {
  return {
    x: (left.x + right.x) / 2,
    y: (left.y + right.y) / 2,
  };
}

function interpolatePoint(left: { x: number; y: number }, right: { x: number; y: number }, t: number) {
  return {
    x: left.x + (right.x - left.x) * t,
    y: left.y + (right.y - left.y) * t,
  };
}

function includePoint(bounds: Bounds, point: { x: number; y: number }) {
  bounds.minX = Math.min(bounds.minX, point.x);
  bounds.minY = Math.min(bounds.minY, point.y);
  bounds.maxX = Math.max(bounds.maxX, point.x);
  bounds.maxY = Math.max(bounds.maxY, point.y);
}

function includeCircle(bounds: Bounds, point: { x: number; y: number }, radius: number) {
  includeRect(bounds, {
    x: point.x - radius,
    y: point.y - radius,
    width: radius * 2,
    height: radius * 2,
  });
}

function includeRect(bounds: Bounds, rect: { x: number; y: number; width: number; height: number }) {
  includePoint(bounds, { x: rect.x, y: rect.y });
  includePoint(bounds, { x: rect.x + rect.width, y: rect.y + rect.height });
}

function copyBounds(bounds: Bounds): Bounds {
  return { ...bounds };
}

function expandBoundsInPlace(bounds: Bounds, padding: number) {
  if (!hasBounds(bounds)) return;
  bounds.minX -= padding;
  bounds.minY -= padding;
  bounds.maxX += padding;
  bounds.maxY += padding;
}

function hasBounds(bounds: Bounds) {
  return Number.isFinite(bounds.minX) && Number.isFinite(bounds.minY) && Number.isFinite(bounds.maxX) && Number.isFinite(bounds.maxY);
}

function radiansToDegrees(value: number) {
  return (value * 180) / Math.PI;
}
