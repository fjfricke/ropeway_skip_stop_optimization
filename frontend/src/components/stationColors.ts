import type { Station } from "../types";

export interface StationVisualColor {
  base: string;
  haloFill: string;
  haloStroke: string;
}

const EXPLICIT_STATION_COLORS: Record<string, StationVisualColor> = {
  l: stationColor("#285aa8", 0.11, 0.2),
  m: stationColor("#1c8c74", 0.1, 0.19),
  r: stationColor("#d97925", 0.1, 0.19),
};

const STATION_PALETTE = [
  stationColor("#1c8c74", 0.1, 0.19),
  stationColor("#7b5fc9", 0.09, 0.18),
  stationColor("#c6476b", 0.085, 0.17),
  stationColor("#607d2f", 0.09, 0.17),
];

export function stationVisualColor(stationId: string, stations?: Station[]): StationVisualColor {
  const key = stationId.toLowerCase();
  const explicit = EXPLICIT_STATION_COLORS[key];
  if (explicit) return explicit;

  const stationIndex = stations?.findIndex((station) => station.id === stationId) ?? -1;
  if (stationIndex >= 0) return STATION_PALETTE[stationIndex % STATION_PALETTE.length];
  return STATION_PALETTE[hashString(key) % STATION_PALETTE.length];
}

function stationColor(base: string, fillAlpha: number, strokeAlpha: number): StationVisualColor {
  return {
    base,
    haloFill: hexToRgba(base, fillAlpha),
    haloStroke: hexToRgba(base, strokeAlpha),
  };
}

function hexToRgba(hex: string, alpha: number) {
  const value = hex.replace("#", "");
  const r = Number.parseInt(value.slice(0, 2), 16);
  const g = Number.parseInt(value.slice(2, 4), 16);
  const b = Number.parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function hashString(value: string) {
  let hash = 0;
  for (const char of value) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return hash;
}
