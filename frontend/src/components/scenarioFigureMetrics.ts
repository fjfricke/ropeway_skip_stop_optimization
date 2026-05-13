import type { PhysicalNode } from "../types";
import type { ViewBoxState } from "./networkTypes";

export const A4_PORTRAIT_300_DPI = {
  width: 2480,
  height: 3508,
};

export const REPORT_TEXT_WIDTH_300_DPI = Math.round((A4_PORTRAIT_300_DPI.width * 147) / 210);

export const FIGURE_FONT_FAMILY = `"TeX Gyre Pagella", "Palatino Linotype", Palatino, serif`;

export type TextSize = {
  width: number;
  height: number;
};

export type NodeLabelPlacementMetrics = {
  scale: number;
  fontSize: number;
  minWidth: number;
  charWidthFactor: number;
  lineHeightFactor: number;
  gaps: number[];
  nodeRadiusDefault: number;
  nodeRadiusPlatform: number;
  labelCollisionPadding: number;
  nodeCollisionPadding: number;
  segmentCollisionPadding: number;
};

export type ScenarioExportVisualMetrics = {
  fontFamily: string;
  shapeScale: number;
  stationLabelFontSize: number;
  nodeLabelFontSize: number;
  demandFontSize: number;
  arcLabelFontSize: number;
  textCharWidthFactor: number;
  lineHeightFactor: number;
  stationLabelStrokeWidth: number;
  nodeLabelStrokeWidth: number;
  stationRadius: number;
  terminalStationRadius: number;
  physicalNodeRadius: number;
  platformNodeRadius: number;
  nodeStrokeWidth: number;
  lineTrackStrokeWidth: number;
  lineTrackHaloWidth: number;
  segmentStrokeWidth: number;
  arrowScale: number;
  arcLabelHeight: number;
  arcLabelPaddingX: number;
  arcLabelRadius: number;
  demandBoxHeight: number;
  demandBoxPaddingX: number;
  demandBoxRadius: number;
  lineStationLabelGap: number;
  lineDemandGap: number;
  boundsPadding: number;
  nodeLabelPlacement: NodeLabelPlacementMetrics;
};

export function screenNodeLabelPlacementMetrics(scale: number): NodeLabelPlacementMetrics {
  return {
    scale,
    fontSize: 12,
    minWidth: 42,
    charWidthFactor: 0.7,
    lineHeightFactor: 1.5,
    gaps: [5, 3, 1, 0, -3, -6, -9, -12],
    nodeRadiusDefault: 9,
    nodeRadiusPlatform: 12,
    labelCollisionPadding: 5,
    nodeCollisionPadding: 4,
    segmentCollisionPadding: 4,
  };
}

export function exportVisualMetrics(viewBox: ViewBoxState, outputWidth: number, baseViewBox: ViewBoxState): ScenarioExportVisualMetrics {
  const userUnitsPerOutputPx = viewBox.width / Math.max(1, outputWidth);
  const ptToUserUnits = (pt: number) => ((pt * 300) / 72) * userUnitsPerOutputPx;
  const stationLabelFontSize = ptToUserUnits(9);
  const nodeLabelFontSize = ptToUserUnits(6);
  const demandFontSize = ptToUserUnits(8);
  const arcLabelFontSize = ptToUserUnits(7.5);
  const textUnit = stationLabelFontSize / 12;
  const shapeScale = viewBox.width / Math.max(1, baseViewBox.width);
  const boundsPadding = Math.max(10 * shapeScale, 6 * textUnit);

  return {
    fontFamily: FIGURE_FONT_FAMILY,
    shapeScale,
    stationLabelFontSize,
    nodeLabelFontSize,
    demandFontSize,
    arcLabelFontSize,
    textCharWidthFactor: 0.62,
    lineHeightFactor: 1.35,
    stationLabelStrokeWidth: 5 * textUnit,
    nodeLabelStrokeWidth: 4 * textUnit,
    stationRadius: 10 * shapeScale,
    terminalStationRadius: 12 * shapeScale,
    physicalNodeRadius: 9 * shapeScale,
    platformNodeRadius: 12 * shapeScale,
    nodeStrokeWidth: 2.5 * shapeScale,
    lineTrackStrokeWidth: 7 * shapeScale,
    lineTrackHaloWidth: 16 * shapeScale,
    segmentStrokeWidth: 5 * shapeScale,
    arrowScale: shapeScale,
    arcLabelHeight: Math.max(21 * textUnit, arcLabelFontSize * 1.55),
    arcLabelPaddingX: 9 * textUnit,
    arcLabelRadius: 4 * textUnit,
    demandBoxHeight: Math.max(24 * textUnit, demandFontSize * 1.75),
    demandBoxPaddingX: 8 * textUnit,
    demandBoxRadius: 5 * textUnit,
    lineStationLabelGap: 14 * shapeScale,
    lineDemandGap: 12 * shapeScale,
    boundsPadding,
    nodeLabelPlacement: {
      scale: 1,
      fontSize: nodeLabelFontSize,
      minWidth: 34 * textUnit,
      charWidthFactor: 0.68,
      lineHeightFactor: 1.35,
      gaps: [5, 3, 1, 0, -3, -6, -9, -12].map((gap) => gap * shapeScale),
      nodeRadiusDefault: 9 * shapeScale,
      nodeRadiusPlatform: 12 * shapeScale,
      labelCollisionPadding: Math.max(5 * shapeScale, 3 * textUnit),
      nodeCollisionPadding: 4 * shapeScale,
      segmentCollisionPadding: 4 * shapeScale,
    },
  };
}

export function physicalNodeRadius(node: PhysicalNode, metrics: Pick<NodeLabelPlacementMetrics, "nodeRadiusDefault" | "nodeRadiusPlatform">) {
  return node.kind === "platform" ? metrics.nodeRadiusPlatform : metrics.nodeRadiusDefault;
}

export function estimateTextSize(
  text: string,
  {
    fontSize,
    minWidth = 0,
    charWidthFactor = 0.62,
    lineHeightFactor = 1.35,
  }: {
    fontSize: number;
    minWidth?: number;
    charWidthFactor?: number;
    lineHeightFactor?: number;
  },
): TextSize {
  return {
    width: Math.max(minWidth, text.length * fontSize * charWidthFactor),
    height: fontSize * lineHeightFactor,
  };
}
