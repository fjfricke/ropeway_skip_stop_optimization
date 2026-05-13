import { forwardRef, useMemo } from "react";
import type { ScenarioLayout } from "../scenarioLayout";
import type { PhysicalNode, Scenario, Station, TrackSegment } from "../types";
import { SegmentSpeedGradient, segmentSpeedColor, segmentSpeedStroke, speedDomainForSegments, speedProfileLabel } from "./arcColor";
import { lineViewPoints, stationLabel } from "./LineViewLayer";
import { pointOnSegment, round } from "./networkGeometry";
import type { SegmentRouteInfo, SpeedDomain } from "./networkTypes";
import {
  aggregateDemandByStation,
  exportSegmentArrowPlacement,
  exportSegmentPath,
  type ExportLineLinkRender,
  type ExportSegmentRender,
  type ScenarioExportRenderPlan,
} from "./scenarioExportGeometry";
import { estimateTextSize, type ScenarioExportVisualMetrics } from "./scenarioFigureMetrics";
import type { ScenarioExportConfig } from "./viewerTypes";

interface ScenarioExportSvgProps {
  scenario: Scenario;
  layout: ScenarioLayout;
  config: ScenarioExportConfig;
  renderPlan: ScenarioExportRenderPlan;
}

export const ScenarioExportSvg = forwardRef<SVGSVGElement, ScenarioExportSvgProps>(function ScenarioExportSvg(
  { scenario, layout, config, renderPlan },
  ref,
) {
  const baseViewBox = useMemo(() => parseViewBox(layout.viewBox), [layout.viewBox]);
  const metrics = renderPlan.metrics;
  const speedDomain = useMemo(() => speedDomainForSegments(scenario.track_segments), [scenario.track_segments]);
  const demandByStation = useMemo(() => aggregateDemandByStation(scenario), [scenario]);

  return (
    <svg
      ref={ref}
      className="scenario-export-svg"
      xmlns="http://www.w3.org/2000/svg"
      width={renderPlan.outputWidth}
      height={renderPlan.outputHeight}
      viewBox={`${round(renderPlan.viewBox.x)} ${round(renderPlan.viewBox.y)} ${round(renderPlan.viewBox.width)} ${round(renderPlan.viewBox.height)}`}
      role="img"
      aria-label={config.displayMode === "line" ? "Scenario line export preview" : "Scenario physical export preview"}
      style={{ fontFamily: metrics.fontFamily }}
    >
      <defs>
        <style>{SCENARIO_EXPORT_SVG_STYLE}</style>
        {config.displayMode === "physical" && config.arcColorMode === "speed"
          ? renderPlan.physicalSegments.map(({ segment }) => (
              <SegmentSpeedGradient key={`${segment.id}-export-speed-gradient`} segment={segment} layout={layout} speedDomain={speedDomain} />
            ))
          : null}
      </defs>

      {config.displayMode === "line" ? (
        <ExportLineLayer
          scenario={scenario}
          baseViewBox={baseViewBox}
          renderPlan={renderPlan}
          showLabels={config.toggles.nodeLabels}
          showDemand={config.toggles.demand}
          demandByStation={demandByStation}
          metrics={metrics}
        />
      ) : (
        <ExportPhysicalLayer scenario={scenario} layout={layout} renderPlan={renderPlan} config={config} speedDomain={speedDomain} metrics={metrics} />
      )}
    </svg>
  );
});

function ExportLineLayer({
  scenario,
  baseViewBox,
  renderPlan,
  showLabels,
  showDemand,
  demandByStation,
  metrics,
}: {
  scenario: Scenario;
  baseViewBox: { x: number; y: number; width: number; height: number };
  renderPlan: ScenarioExportRenderPlan;
  showLabels: boolean;
  showDemand: boolean;
  demandByStation: Map<string, number>;
  metrics: ScenarioExportVisualMetrics;
}) {
  const points = lineViewPoints(scenario, baseViewBox);
  const pointByStation = new Map(points.map((point) => [point.station.id, point]));
  return (
    <g className="line-view" aria-label="Schematic station line">
      {renderPlan.lineLinks.map((link) => (
        <ExportLineLink key={link.id} link={link} metrics={metrics} />
      ))}
      {points.map(({ station }) => {
        const point = pointByStation.get(station.id);
        if (!point || !renderPlan.lineStations.has(station.id)) return null;
        const radius = lineStationRadius(station, metrics);
        const labelSize = estimateTextSize(stationLabel(station), {
          fontSize: metrics.stationLabelFontSize,
          charWidthFactor: metrics.textCharWidthFactor,
          lineHeightFactor: metrics.lineHeightFactor,
        });
        const demandCount = demandByStation.get(station.id) ?? 0;
        return (
          <g key={station.id} className={`line-view-station line-view-station--${station.kind}`} transform={`translate(${point.x} ${point.y})`}>
            <circle r={radius} strokeWidth={metrics.nodeStrokeWidth} />
            {showLabels ? (
              <text
                x="0"
                y={-radius - metrics.lineStationLabelGap - labelSize.height / 2}
                style={{ fontSize: metrics.stationLabelFontSize, strokeWidth: metrics.stationLabelStrokeWidth }}
                dominantBaseline="central"
              >
                {stationLabel(station)}
              </text>
            ) : null}
            {showDemand && demandCount > 0 ? (
              <g className="line-view-demand" transform={`translate(0 ${radius + metrics.lineDemandGap + metrics.demandBoxHeight / 2})`}>
                <ExportDemandBox text={`${demandCount} pax`} metrics={metrics} />
              </g>
            ) : null}
          </g>
        );
      })}
    </g>
  );
}

function ExportLineLink({ link, metrics }: { link: ExportLineLinkRender; metrics: ScenarioExportVisualMetrics }) {
  const midpoint = {
    x: (link.from.x + link.to.x) / 2,
    y: (link.from.y + link.to.y) / 2,
  };
  const from = link.mode === "from_end" ? midpoint : link.from;
  const to = link.mode === "from_start" ? midpoint : link.to;
  const path = `M ${round(from.x)} ${round(from.y)} L ${round(to.x)} ${round(to.y)}`;
  return (
    <>
      <path className="line-view__track-halo" d={path} strokeWidth={metrics.lineTrackHaloWidth} />
      <path className="line-view__track" d={path} strokeWidth={metrics.lineTrackStrokeWidth} />
    </>
  );
}

function ExportDemandBox({ text, metrics }: { text: string; metrics: ScenarioExportVisualMetrics }) {
  const textSize = estimateTextSize(text, {
    fontSize: metrics.demandFontSize,
    charWidthFactor: metrics.textCharWidthFactor,
    lineHeightFactor: metrics.lineHeightFactor,
  });
  const width = Math.max(metrics.demandBoxHeight * 2.25, textSize.width + metrics.demandBoxPaddingX * 2);
  return (
    <>
      <rect x={-width / 2} y={-metrics.demandBoxHeight / 2} width={width} height={metrics.demandBoxHeight} rx={metrics.demandBoxRadius} strokeWidth={metrics.nodeStrokeWidth / 2} />
      <text x="0" y="0" style={{ fontSize: metrics.demandFontSize }} dominantBaseline="central">
        {text}
      </text>
    </>
  );
}

function ExportPhysicalLayer({
  scenario,
  layout,
  renderPlan,
  config,
  speedDomain,
  metrics,
}: {
  scenario: Scenario;
  layout: ScenarioLayout;
  renderPlan: ScenarioExportRenderPlan;
  config: ScenarioExportConfig;
  speedDomain: SpeedDomain;
  metrics: ScenarioExportVisualMetrics;
}) {
  return (
    <>
      <g className="layer layer--infrastructure">
        {renderPlan.physicalSegments.map((segmentRender) => (
          <ExportSegmentPath
            key={segmentRender.segment.id}
            segmentRender={segmentRender}
            layout={layout}
            arcColorMode={config.arcColorMode}
            speedDomain={speedDomain}
            metrics={metrics}
          />
        ))}
        {renderPlan.physicalSegments.map((segmentRender) => (
          <ExportSegmentArrow
            key={`${segmentRender.segment.id}-arrow`}
            segmentRender={segmentRender}
            layout={layout}
            arcColorMode={config.arcColorMode}
            speedDomain={speedDomain}
            metrics={metrics}
          />
        ))}
      </g>

      {config.toggles.arcLabels ? (
        <g className="layer layer--annotations">
          {renderPlan.physicalSegments.map((segmentRender) =>
            segmentRender.canRenderLabel ? (
              <ExportSegmentLabel
                key={`${segmentRender.segment.id}-label`}
                segment={segmentRender.segment}
                routeInfo={segmentRender.routeInfo}
                layout={layout}
                arcColorMode={config.arcColorMode}
                metrics={metrics}
              />
            ) : null,
          )}
        </g>
      ) : null}

      <g className="layer layer--nodes">
        {scenario.physical_nodes.map((node) => {
          if (!renderPlan.physicalNodes.has(node.id)) return null;
          const point = layout.nodes[node.id];
          if (!point) return null;
          return (
            <g key={node.id} className={`node node--${node.kind}`} transform={`translate(${point.x} ${point.y})`}>
              <ExportNodeShape node={node} metrics={metrics} />
            </g>
          );
        })}
      </g>

      {config.toggles.nodeLabels ? (
        <g className="layer layer--node-labels">
          {scenario.physical_nodes.map((node) => {
            if (!renderPlan.physicalNodes.has(node.id)) return null;
            const point = layout.nodes[node.id];
            if (!point) return null;
            const labelPlacement = renderPlan.physicalNodeLabelPlacements.get(node.id) ?? { dx: 0, dy: -28 * metrics.shapeScale };
            return (
              <g key={`${node.id}-label`} className="node-label" transform={`translate(${point.x} ${point.y})`}>
                <text
                  x={labelPlacement.dx}
                  y={labelPlacement.dy}
                  style={{ fontSize: metrics.nodeLabelFontSize, strokeWidth: metrics.nodeLabelStrokeWidth }}
                  textAnchor="middle"
                  dominantBaseline="central"
                >
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

function ExportNodeShape({ node, metrics }: { node: PhysicalNode; metrics: ScenarioExportVisualMetrics }) {
  const radius = node.kind === "platform" ? metrics.platformNodeRadius : metrics.physicalNodeRadius;
  if (node.kind.includes("switch")) {
    const scale = metrics.shapeScale;
    return <path d={`M 0 ${-10 * scale} L ${12 * scale} ${10 * scale} L ${-12 * scale} ${10 * scale} Z`} strokeWidth={metrics.nodeStrokeWidth} />;
  }
  return <circle r={radius} strokeWidth={metrics.nodeStrokeWidth} />;
}

function ExportSegmentPath({
  segmentRender,
  layout,
  arcColorMode,
  speedDomain,
  metrics,
}: {
  segmentRender: ExportSegmentRender;
  layout: ScenarioLayout;
  arcColorMode: "type" | "speed";
  speedDomain: SpeedDomain;
  metrics: ScenarioExportVisualMetrics;
}) {
  const { segment, routeInfo, mode } = segmentRender;
  const speedStroke = arcColorMode === "speed" ? segmentSpeedStroke(segment, speedDomain) : undefined;
  const strokeStyle: { stroke?: string; strokeDasharray?: string } = {};
  if (speedStroke) strokeStyle.stroke = speedStroke;
  if (segment.kind === "skip") strokeStyle.strokeDasharray = `${12 * metrics.shapeScale} ${8 * metrics.shapeScale}`;
  return (
    <path
      className={`segment segment--${segment.kind} route--${routeInfo?.routeKind ?? "rope"}`}
      d={exportSegmentPath(segment, layout, mode)}
      style={Object.keys(strokeStyle).length > 0 ? strokeStyle : undefined}
      strokeWidth={metrics.segmentStrokeWidth}
    />
  );
}

function ExportSegmentArrow({
  segmentRender,
  layout,
  arcColorMode,
  speedDomain,
  metrics,
}: {
  segmentRender: ExportSegmentRender;
  layout: ScenarioLayout;
  arcColorMode: "type" | "speed";
  speedDomain: SpeedDomain;
  metrics: ScenarioExportVisualMetrics;
}) {
  const { segment, mode } = segmentRender;
  const arrow = exportSegmentArrowPlacement(segment, layout, mode);
  if (!arrow) return null;
  const speedFill = arcColorMode === "speed" ? segmentSpeedColor(segment, speedDomain, arrow.t) : undefined;
  const outer = arrowPath(metrics.arrowScale, 13, 8, 7);
  const inner = arrowPath(metrics.arrowScale, 11, 6, 5);
  return (
    <g transform={`translate(${arrow.x} ${arrow.y}) rotate(${arrow.angleDeg})`}>
      <path className="segment-arrow__halo" d={outer} strokeWidth={metrics.nodeStrokeWidth / 2} />
      <path className={`segment-arrow segment-arrow--${segment.kind}`} d={inner} style={speedFill ? { fill: speedFill } : undefined} strokeWidth={metrics.nodeStrokeWidth / 2} />
    </g>
  );
}

function ExportSegmentLabel({
  segment,
  routeInfo,
  layout,
  arcColorMode,
  metrics,
}: {
  segment: TrackSegment;
  routeInfo?: SegmentRouteInfo;
  layout: ScenarioLayout;
  arcColorMode: "type" | "speed";
  metrics: ScenarioExportVisualMetrics;
}) {
  const midpoint = pointOnSegment(segment, layout, 0.5);
  if (!midpoint) return null;
  const typeLabel = routeInfo?.routeKind === "skip" ? "skip" : segment.kind;
  const label = arcColorMode === "speed" ? speedProfileLabel(segment.speed_profile) : typeLabel;
  const text = `${label} · ${segment.length_m}m`;
  const textSize = estimateTextSize(text, {
    fontSize: metrics.arcLabelFontSize,
    charWidthFactor: metrics.textCharWidthFactor,
    lineHeightFactor: metrics.lineHeightFactor,
  });
  const boxWidth = Math.max(76 * metrics.arrowScale, textSize.width + metrics.arcLabelPaddingX * 2);
  return (
    <g className={`segment-label segment-label--${routeInfo?.routeKind ?? segment.kind}`} transform={`translate(${midpoint.x} ${midpoint.y})`}>
      <rect x={-boxWidth / 2} y={-metrics.arcLabelHeight / 2} width={boxWidth} height={metrics.arcLabelHeight} rx={metrics.arcLabelRadius} strokeWidth={metrics.nodeStrokeWidth / 2} />
      <text x="0" y="0" style={{ fontSize: metrics.arcLabelFontSize }} dominantBaseline="central">
        {text}
      </text>
    </g>
  );
}

function lineStationRadius(station: Station, metrics: ScenarioExportVisualMetrics) {
  return station.kind === "terminal" ? metrics.terminalStationRadius : metrics.stationRadius;
}

function arrowPath(scale: number, backX: number, halfHeight: number, tipX: number) {
  return `M ${-backX * scale} ${-halfHeight * scale} L ${tipX * scale} 0 L ${-backX * scale} ${halfHeight * scale} Z`;
}

function parseViewBox(value: string) {
  const [x, y, width, height] = value.split(/\s+/).map(Number);
  return { x, y, width, height };
}

export const SCENARIO_EXPORT_SVG_STYLE = `
.segment{fill:none;stroke-linecap:round;stroke-linejoin:round}
.segment--rope{stroke:#627184}
.segment--station{stroke:#1c8c74}
.segment--connector{stroke:#8a6680}
.segment--skip{stroke:#d97925;stroke-dasharray:12 8}
.segment-arrow{pointer-events:none;stroke:rgba(255,255,255,.94);stroke-linejoin:round;filter:drop-shadow(0 1px 1px rgba(23,32,43,.22))}
.segment-arrow__halo{pointer-events:none;fill:rgba(255,255,255,.96);stroke:rgba(23,32,43,.18);stroke-linejoin:round}
.segment-arrow--rope{fill:#627184}
.segment-arrow--station{fill:#1c8c74}
.segment-arrow--connector{fill:#8a6680}
.segment-arrow--skip{fill:#d97925}
.line-view__track-halo,.line-view__track{fill:none;stroke-linecap:round;stroke-linejoin:round}
.line-view__track-halo{stroke:rgba(255,255,255,.96)}
.line-view__track{stroke:#1c8c74}
.line-view-station circle{fill:#fff;stroke:#1c8c74}
.line-view-station--terminal circle{fill:#edf5ff;stroke:#253345}
.line-view-station text{fill:#17202b;font-weight:720;letter-spacing:0;text-anchor:middle;paint-order:stroke;stroke:rgba(255,255,255,.86)}
.line-view-demand rect{fill:#fff7ed;stroke:rgba(217,121,37,.38)}
.line-view-demand text{fill:#8a4b12;font-weight:820;letter-spacing:0;text-anchor:middle;paint-order:normal;stroke:none}
.segment-label{pointer-events:none}
.segment-label rect{fill:rgba(255,255,255,.7);stroke:rgba(101,113,127,.25)}
.segment-label text{fill:#41505f;font-weight:750;text-anchor:middle}
.node circle,.node path{fill:#fff;stroke:#253345}
.node--platform circle,.node--platform path{fill:#e5f4ee;stroke:#1c8c74}
.node--entry_switch circle,.node--entry_switch path,.node--exit_switch circle,.node--exit_switch path{fill:#fff2df;stroke:#d97925}
.node-label{pointer-events:none}
.node-label text{fill:#17202b;font-weight:600;letter-spacing:0;paint-order:stroke;stroke:rgba(255,255,255,.8)}
`;
