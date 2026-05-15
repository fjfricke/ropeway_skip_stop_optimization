import { differenceCiede2000, displayable, formatHex } from "culori";
import type { Oklch } from "culori";
import type { Station } from "../types";

export interface StationVisualColor {
  base: string;
  haloFill: string;
  haloStroke: string;
}

interface StationColorCandidate {
  color: Oklch;
  hex: string;
}

const HALO_FILL_ALPHA = 0.1;
const HALO_STROKE_ALPHA = 0.19;
const FALLBACK_PALETTE_SIZE = 16;
const HUE_DISTANCE_WEIGHT = 0.35;
const paletteCache = new Map<string, StationVisualColor[]>();
const colorDistance = differenceCiede2000();
const colorCandidates = buildColorCandidates();
const fallbackPalette = selectDistinctCandidates(FALLBACK_PALETTE_SIZE).map((candidate) => stationColor(candidate.hex));

export function stationVisualColor(stationId: string, stations?: Station[]): StationVisualColor {
  const key = stationId.toLowerCase();
  if (stations?.length) {
    const stationIndex = stations.findIndex((station) => station.id.toLowerCase() === key);
    if (stationIndex >= 0) return stationPalette(stations)[stationIndex];
  }
  return fallbackPalette[hashString(key) % fallbackPalette.length];
}

function stationPalette(stations: Station[]): StationVisualColor[] {
  const cacheKey = stations.map((station) => station.id.toLowerCase()).join("|");
  const cached = paletteCache.get(cacheKey);
  if (cached) return cached;

  const palette = selectDistinctCandidates(stations.length).map((candidate) => stationColor(candidate.hex));
  paletteCache.set(cacheKey, palette);
  return palette;
}

function selectDistinctCandidates(count: number): StationColorCandidate[] {
  if (count <= 0) return [];
  const selected = [colorCandidates[0]];
  const remaining = colorCandidates.slice(1);

  while (selected.length < count && remaining.length) {
    let bestIndex = 0;
    let bestDistance = Number.NEGATIVE_INFINITY;

    for (let index = 0; index < remaining.length; index += 1) {
      const candidate = remaining[index];
      const minDistance = Math.min(...selected.map((selectedCandidate) => colorDistance(candidate.color, selectedCandidate.color)));
      const minHueDistance = Math.min(...selected.map((selectedCandidate) => hueDistance(candidate.color.h, selectedCandidate.color.h)));
      const distinctnessScore = minDistance + Math.min(minHueDistance, 90) * HUE_DISTANCE_WEIGHT;
      if (distinctnessScore > bestDistance) {
        bestDistance = distinctnessScore;
        bestIndex = index;
      }
    }

    selected.push(remaining.splice(bestIndex, 1)[0]);
  }

  return selected;
}

function buildColorCandidates(): StationColorCandidate[] {
  const hues = preferredHueOrder(15);
  const lightnesses = [0.56, 0.66, 0.48, 0.72, 0.61];
  const chromas = [0.155, 0.125, 0.18, 0.105];
  const candidates: StationColorCandidate[] = [];
  const seen = new Set<string>();

  for (const lightness of lightnesses) {
    for (const chroma of chromas) {
      for (const hue of hues) {
        const color: Oklch = { mode: "oklch", l: lightness, c: chroma, h: hue };
        if (!displayable(color)) continue;
        const hex = formatHex(color)?.toLowerCase();
        if (!hex || seen.has(hex)) continue;
        seen.add(hex);
        candidates.push({ color, hex });
      }
    }
  }

  return candidates;
}

function preferredHueOrder(stepDegrees: number): number[] {
  const startHue = 220;
  const count = Math.floor(360 / stepDegrees);
  return Array.from({ length: count }, (_, index) => (startHue + index * stepDegrees) % 360);
}

function hueDistance(left = 0, right = 0): number {
  const distance = Math.abs(((left - right + 180) % 360) - 180);
  return Number.isNaN(distance) ? 0 : distance;
}

function stationColor(base: string): StationVisualColor {
  return {
    base,
    haloFill: hexToRgba(base, HALO_FILL_ALPHA),
    haloStroke: hexToRgba(base, HALO_STROKE_ALPHA),
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
