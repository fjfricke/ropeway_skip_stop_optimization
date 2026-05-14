import { useId } from "react";
import type { CSSProperties } from "react";
import type { ScenarioLayout } from "../scenarioLayout";
import type { Scenario } from "../types";
import { stationVisualColor } from "./stationColors";
import { stationZoneBounds } from "./stationZoneGeometry";

export function StationZoneLayer({
  scenario,
  layout,
  scale,
  stationIds,
  renderMode = "blur",
}: {
  scenario: Scenario;
  layout: ScenarioLayout;
  scale: number;
  stationIds?: Set<string>;
  renderMode?: "blur" | "stacked";
}) {
  const filterId = `station-zone-blur-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const blurRadius = 12 * scale;

  return (
    <g className="layer layer--station-zones" aria-hidden="true">
      {renderMode === "blur" ? (
        <defs>
          <filter id={filterId} x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation={blurRadius} />
          </filter>
        </defs>
      ) : null}
      {scenario.stations.map((station) => {
        if (stationIds && !stationIds.has(station.id)) return null;
        const bounds = stationZoneBounds(station.id, scenario, layout);
        if (!bounds) return null;
        const paddingX = 34 * scale;
        const paddingY = 28 * scale;
        const color = stationVisualColor(station.id, scenario.stations);
        const rect = {
          x: bounds.minX - paddingX,
          y: bounds.minY - paddingY,
          width: bounds.maxX - bounds.minX + paddingX * 2,
          height: bounds.maxY - bounds.minY + paddingY * 2,
          rx: 18 * scale,
        };
        if (renderMode === "stacked") {
          const layers = [
            { expand: 18 * scale, opacity: 0.008 },
            { expand: 12 * scale, opacity: 0.012 },
            { expand: 7 * scale, opacity: 0.018 },
            { expand: 2 * scale, opacity: 0.032 },
          ];
          return (
            <g key={station.id}>
              {layers.map((layer, index) => (
                <rect
                  key={`${station.id}-${index}`}
                  className="station-zone-fringe"
                  x={rect.x - layer.expand}
                  y={rect.y - layer.expand}
                  width={rect.width + layer.expand * 2}
                  height={rect.height + layer.expand * 2}
                  rx={rect.rx + layer.expand}
                  fill={color.base}
                  opacity={layer.opacity}
                  vectorEffect="non-scaling-stroke"
                />
              ))}
            </g>
          );
        }
        return (
          <rect
            key={station.id}
            className="station-zone"
            x={rect.x}
            y={rect.y}
            width={rect.width}
            height={rect.height}
            rx={rect.rx}
            filter={`url(#${filterId})`}
            style={{ "--station-zone-fill": color.haloFill, "--station-zone-stroke": color.haloStroke } as CSSProperties}
            vectorEffect="non-scaling-stroke"
          />
        );
      })}
    </g>
  );
}
