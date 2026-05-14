import type { ScenarioLayout } from "../scenarioLayout";
import type { Scenario } from "../types";
import { stationLabel } from "./LineViewLayer";
import type { ViewBoxState } from "./networkTypes";
import { estimateTextSize, type ScenarioExportVisualMetrics } from "./scenarioFigureMetrics";
import { stationContentPlacement } from "./stationPlacement";

export type StationNamePlacement = {
  stationId: string;
  label: string;
  x: number;
  y: number;
  width: number;
  height: number;
};

export function stationNamePlacements({
  scenario,
  layout,
  viewBox,
  stationIds,
  scale,
  fontSize,
  charWidthFactor = 0.62,
  lineHeightFactor = 1.35,
}: {
  scenario: Scenario;
  layout: ScenarioLayout;
  viewBox: ViewBoxState;
  stationIds: Set<string>;
  scale: number;
  fontSize: number;
  charWidthFactor?: number;
  lineHeightFactor?: number;
}): StationNamePlacement[] {
  return scenario.stations.flatMap((station) => {
    if (!stationIds.has(station.id)) return [];
    const label = stationLabel(station);
    const textSize = estimateTextSize(label, { fontSize, charWidthFactor, lineHeightFactor });
    const baseSize = {
      width: textSize.width / Math.max(scale, 1e-9),
      height: textSize.height / Math.max(scale, 1e-9),
    };
    const point = stationContentPlacement(station.id, scenario, layout, viewBox, baseSize, scale);
    if (!point) return [];
    return [{
      stationId: station.id,
      label,
      x: point.x,
      y: point.y,
      width: textSize.width,
      height: textSize.height,
    }];
  });
}

export function stationNameFontSize(metrics: ScenarioExportVisualMetrics) {
  return metrics.stationLabelFontSize;
}
