import type { ScenarioLayout } from "../scenarioLayout";
import type { DiscreteNode, TrackSegment } from "../types";
import type { ViewBoxState } from "./networkTypes";

export const MAX_VIEWBOX_SCALE = 1.8;

export function segmentPath(segment: TrackSegment, layout: ScenarioLayout) {
  const from = layout.nodes[segment.from_node_id];
  const to = layout.nodes[segment.to_node_id];
  if (!from || !to) return "";
  const curve = layout.segments[segment.id]?.curve ?? 0;
  if (curve === 0) return `M ${from.x} ${from.y} L ${to.x} ${to.y}`;
  const midX = (from.x + to.x) / 2;
  const midY = (from.y + to.y) / 2 + curve;
  return `M ${from.x} ${from.y} Q ${midX} ${midY} ${to.x} ${to.y}`;
}

export function discreteNodePoint(
  node: DiscreteNode,
  layout: ScenarioLayout,
  segmentById: Map<string, TrackSegment>,
): { x: number; y: number } | null {
  if (node.source_physical_node_id) {
    return layout.nodes[node.source_physical_node_id] ?? null;
  }
  if (!node.source_segment_id || node.position_m === null) return null;
  const segment = segmentById.get(node.source_segment_id);
  if (!segment) return null;
  return pointOnSegment(segment, layout, node.position_m / segment.length_m);
}

export function pointOnSegment(segment: TrackSegment, layout: ScenarioLayout, rawT: number) {
  const from = layout.nodes[segment.from_node_id];
  const to = layout.nodes[segment.to_node_id];
  const t = clamp(rawT, 0, 1);
  if (!from || !to) return null;
  const curve = layout.segments[segment.id]?.curve ?? 0;
  if (curve === 0) {
    return {
      x: from.x + (to.x - from.x) * t,
      y: from.y + (to.y - from.y) * t,
    };
  }

  const control = {
    x: (from.x + to.x) / 2,
    y: (from.y + to.y) / 2 + curve,
  };
  const oneMinusT = 1 - t;
  return {
    x: oneMinusT * oneMinusT * from.x + 2 * oneMinusT * t * control.x + t * t * to.x,
    y: oneMinusT * oneMinusT * from.y + 2 * oneMinusT * t * control.y + t * t * to.y,
  };
}

export function segmentTangentAngle(segment: TrackSegment, layout: ScenarioLayout, rawT: number) {
  const from = layout.nodes[segment.from_node_id];
  const to = layout.nodes[segment.to_node_id];
  const t = clamp(rawT, 0, 1);
  if (!from || !to) return 0;
  const curve = layout.segments[segment.id]?.curve ?? 0;
  if (curve === 0) {
    return radiansToDegrees(Math.atan2(to.y - from.y, to.x - from.x));
  }

  const control = {
    x: (from.x + to.x) / 2,
    y: (from.y + to.y) / 2 + curve,
  };
  const oneMinusT = 1 - t;
  const dx = 2 * oneMinusT * (control.x - from.x) + 2 * t * (to.x - control.x);
  const dy = 2 * oneMinusT * (control.y - from.y) + 2 * t * (to.y - control.y);
  return radiansToDegrees(Math.atan2(dy, dx));
}

export function waitArcPath(point: { x: number; y: number }, inverseZoom: number) {
  const radius = 9 * inverseZoom;
  return [
    `M ${round(point.x + radius)} ${round(point.y)}`,
    `C ${round(point.x + radius)} ${round(point.y - radius)}`,
    `${round(point.x - radius)} ${round(point.y - radius)}`,
    `${round(point.x - radius)} ${round(point.y)}`,
    `C ${round(point.x - radius)} ${round(point.y + radius)}`,
    `${round(point.x + radius)} ${round(point.y + radius)}`,
    `${round(point.x + radius)} ${round(point.y)}`,
  ].join(" ");
}

export function segmentArrowPlacement(segment: TrackSegment, layout: ScenarioLayout) {
  const from = layout.nodes[segment.from_node_id];
  const to = layout.nodes[segment.to_node_id];
  if (!from || !to) return null;
  const curve = layout.segments[segment.id]?.curve ?? 0;
  const t = 0.7;
  if (curve === 0) {
    const x = from.x + (to.x - from.x) * t;
    const y = from.y + (to.y - from.y) * t;
    const angleDeg = radiansToDegrees(Math.atan2(to.y - from.y, to.x - from.x));
    return { x, y, angleDeg, t };
  }

  const control = {
    x: (from.x + to.x) / 2,
    y: (from.y + to.y) / 2 + curve,
  };
  const oneMinusT = 1 - t;
  const x = oneMinusT * oneMinusT * from.x + 2 * oneMinusT * t * control.x + t * t * to.x;
  const y = oneMinusT * oneMinusT * from.y + 2 * oneMinusT * t * control.y + t * t * to.y;
  const dx = 2 * oneMinusT * (control.x - from.x) + 2 * t * (to.x - control.x);
  const dy = 2 * oneMinusT * (control.y - from.y) + 2 * t * (to.y - control.y);
  return { x, y, angleDeg: radiansToDegrees(Math.atan2(dy, dx)), t };
}

export function parseViewBox(value: string): ViewBoxState {
  const [x, y, width, height] = value.split(/\s+/).map(Number);
  return { x, y, width, height };
}

export function formatViewBox(value: ViewBoxState) {
  return `${round(value.x)} ${round(value.y)} ${round(value.width)} ${round(value.height)}`;
}

export function round(value: number) {
  return Math.round(value * 1000) / 1000;
}

export function clientToViewBoxPoint(clientX: number, clientY: number, rect: DOMRect, viewBox: ViewBoxState) {
  return {
    x: viewBox.x + ((clientX - rect.left) / rect.width) * viewBox.width,
    y: viewBox.y + ((clientY - rect.top) / rect.height) * viewBox.height,
  };
}

export function zoomViewBox(
  current: ViewBoxState,
  base: ViewBoxState,
  center: { x: number; y: number },
  scaleFactor: number,
  minViewBoxScale: number,
) {
  const targetWidth = clamp(current.width * scaleFactor, base.width * minViewBoxScale, base.width * MAX_VIEWBOX_SCALE);
  const targetHeight = targetWidth * (base.height / base.width);
  const ratioX = (center.x - current.x) / current.width;
  const ratioY = (center.y - current.y) / current.height;
  return clampViewBox(
    {
      x: center.x - targetWidth * ratioX,
      y: center.y - targetHeight * ratioY,
      width: targetWidth,
      height: targetHeight,
    },
    base,
  );
}

export function clampViewBox(value: ViewBoxState, base: ViewBoxState) {
  const marginX = base.width * 0.45;
  const marginY = base.height * 0.45;
  return {
    ...value,
    x: clamp(value.x, base.x - marginX, base.x + base.width + marginX - value.width),
    y: clamp(value.y, base.y - marginY, base.y + base.height + marginY - value.height),
  };
}

export function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function radiansToDegrees(value: number) {
  return (value * 180) / Math.PI;
}
