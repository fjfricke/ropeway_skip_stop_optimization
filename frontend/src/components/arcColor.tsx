import type { ScenarioLayout } from "../scenarioLayout";
import type { SpeedProfile, TrackSegment } from "../types";
import { clamp } from "./networkGeometry";
import type { SpeedDomain } from "./networkTypes";

export function SegmentSpeedGradient({ segment, layout, speedDomain }: { segment: TrackSegment; layout: ScenarioLayout; speedDomain: SpeedDomain }) {
  const speeds = segmentSpeedEndpoints(segment);
  const from = layout.nodes[segment.from_node_id];
  const to = layout.nodes[segment.to_node_id];
  if (!speeds || speeds.start === speeds.end || !from || !to) return null;
  return (
    <linearGradient id={segmentSpeedGradientId(segment)} gradientUnits="userSpaceOnUse" x1={from.x} y1={from.y} x2={to.x} y2={to.y}>
      <stop offset="0%" stopColor={speedToColor(speeds.start, speedDomain)} />
      <stop offset="100%" stopColor={speedToColor(speeds.end, speedDomain)} />
    </linearGradient>
  );
}

export function speedDomainForSegments(segments: TrackSegment[]): SpeedDomain {
  const speeds = segments.flatMap((segment) => segmentSpeedValues(segment));
  if (speeds.length === 0) return { min: 0, max: 1 };
  return {
    min: Math.min(...speeds),
    max: Math.max(...speeds),
  };
}

export function segmentSpeedStroke(segment: TrackSegment, speedDomain: SpeedDomain) {
  const speeds = segmentSpeedEndpoints(segment);
  if (!speeds) return undefined;
  if (speeds.start !== speeds.end) return `url(#${segmentSpeedGradientId(segment)})`;
  return speedToColor(speeds.start, speedDomain);
}

export function segmentSpeedColor(segment: TrackSegment, speedDomain: SpeedDomain, t: number) {
  const speeds = segmentSpeedEndpoints(segment);
  if (!speeds) return undefined;
  return speedToColor(speeds.start + (speeds.end - speeds.start) * t, speedDomain);
}

export function speedProfileLabel(profile: SpeedProfile | null) {
  if (!profile) return "speed n/a";
  if (profile.kind === "constant") return `${formatSpeed(profile.speed_m_per_s)} m/s`;
  return `${formatSpeed(profile.start_speed_m_per_s)} -> ${formatSpeed(profile.end_speed_m_per_s)} m/s`;
}

function segmentSpeedValues(segment: TrackSegment) {
  const endpoints = segmentSpeedEndpoints(segment);
  return endpoints ? [endpoints.start, endpoints.end] : [];
}

function segmentSpeedEndpoints(segment: TrackSegment) {
  const profile = segment.speed_profile;
  if (!profile) return null;
  if (profile.kind === "constant") {
    if (!isNumber(profile.speed_m_per_s)) return null;
    return { start: profile.speed_m_per_s, end: profile.speed_m_per_s };
  }
  if (!isNumber(profile.start_speed_m_per_s) || !isNumber(profile.end_speed_m_per_s)) return null;
  return { start: profile.start_speed_m_per_s, end: profile.end_speed_m_per_s };
}

function speedToColor(speed: number, domain: SpeedDomain) {
  const ratio = domain.max === domain.min ? 0.5 : clamp((speed - domain.min) / (domain.max - domain.min), 0, 1);
  const slow: [number, number, number] = [42, 111, 187];
  const fast: [number, number, number] = [194, 65, 12];
  const channel = (index: number) => Math.round(slow[index] + (fast[index] - slow[index]) * ratio);
  return `rgb(${channel(0)}, ${channel(1)}, ${channel(2)})`;
}

function formatSpeed(value: number | null) {
  if (value === null) return "n/a";
  return String(Math.round(value * 10) / 10);
}

function segmentSpeedGradientId(segment: TrackSegment) {
  return `segment-speed-${segment.id.replace(/[^a-zA-Z0-9_-]/g, "_")}`;
}

function isNumber(value: number | null): value is number {
  return typeof value === "number" && Number.isFinite(value);
}
