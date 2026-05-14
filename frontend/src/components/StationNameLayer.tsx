import type { ScenarioLayout } from "../scenarioLayout";
import type { Scenario } from "../types";
import type { ViewBoxState } from "./networkTypes";
import { stationNamePlacements } from "./stationNamePlacement";

export function StationNameLayer({
  scenario,
  layout,
  viewBox,
  stationIds,
  scale,
  fontSize,
  strokeWidth,
  charWidthFactor = 0.62,
  lineHeightFactor = 1.35,
}: {
  scenario: Scenario;
  layout: ScenarioLayout;
  viewBox: ViewBoxState;
  stationIds: Set<string>;
  scale: number;
  fontSize: number;
  strokeWidth: number;
  charWidthFactor?: number;
  lineHeightFactor?: number;
}) {
  const placements = stationNamePlacements({
    scenario,
    layout,
    viewBox,
    stationIds,
    scale,
    fontSize,
    charWidthFactor,
    lineHeightFactor,
  });
  if (placements.length === 0) return null;

  return (
    <g className="layer layer--station-names" aria-label="Station names">
      {placements.map((placement) => (
        <text
          key={placement.stationId}
          className="station-name-label"
          x={placement.x + placement.width / 2}
          y={placement.y + placement.height / 2}
          style={{ fontSize, strokeWidth }}
          textAnchor="middle"
          dominantBaseline="central"
        >
          {placement.label}
        </text>
      ))}
    </g>
  );
}
