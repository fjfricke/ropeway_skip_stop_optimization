import type { Scenario, Station } from "../types";
import { round } from "./networkGeometry";
import type { ViewBoxState } from "./networkTypes";

export function LineViewLayer({
  scenario,
  viewBox,
  showLabels,
  showDemand,
  demandByStation,
  inverseZoom,
}: {
  scenario: Scenario;
  viewBox: ViewBoxState;
  showLabels: boolean;
  showDemand: boolean;
  demandByStation: Map<string, number>;
  inverseZoom: number;
}) {
  const stations = scenario.stations.filter((station) => station.kind === "terminal" || station.kind === "service");
  if (stations.length === 0) return null;

  const marginX = Math.min(150, viewBox.width * 0.14);
  const y = viewBox.y + viewBox.height * 0.52;
  const usableWidth = viewBox.width - 2 * marginX;
  const step = stations.length > 1 ? usableWidth / (stations.length - 1) : 0;
  const points = stations.map((station, index) => ({
    station,
    x: viewBox.x + marginX + step * index,
    y,
  }));
  const path = points.map((point, index) => `${index === 0 ? "M" : "L"} ${round(point.x)} ${round(point.y)}`).join(" ");

  return (
    <g className="line-view" aria-label="Schematic station line">
      {points.length > 1 ? (
        <>
          <path className="line-view__track-halo" d={path} />
          <path className="line-view__track" d={path} />
        </>
      ) : null}
      {points.map(({ station, x, y }) => (
        <LineViewStation
          key={station.id}
          station={station}
          x={x}
          y={y}
          showLabels={showLabels}
          showDemand={showDemand}
          demandCount={demandByStation.get(station.id) ?? 0}
          inverseZoom={inverseZoom}
        />
      ))}
    </g>
  );
}

function LineViewStation({
  station,
  x,
  y,
  showLabels,
  showDemand,
  demandCount,
  inverseZoom,
}: {
  station: Station;
  x: number;
  y: number;
  showLabels: boolean;
  showDemand: boolean;
  demandCount: number;
  inverseZoom: number;
}) {
  const radius = station.kind === "terminal" ? 12 : 10;
  const labelOffset = radius + 14;
  const demandOffset = radius + 14 + 12;
  return (
    <g className={`line-view-station line-view-station--${station.kind}`} transform={`translate(${x} ${y}) scale(${inverseZoom})`}>
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
}

function stationLabel(station: Station) {
  return station.name?.trim() || station.id;
}
