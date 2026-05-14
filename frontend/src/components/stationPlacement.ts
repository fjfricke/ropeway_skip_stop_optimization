import type { ScenarioLayout } from "../scenarioLayout";
import type { Scenario, TrackSegment } from "../types";
import { pointOnSegment } from "./networkGeometry";
import type { ViewBoxState } from "./networkTypes";

export type PlacementRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

const STATION_PLACEMENT_GAP = 18;
const STATION_BOX_PADDING = 18;
const STATION_NODE_RADIUS = 12;

export function stationContentPlacement(
  stationId: string,
  scenario: Scenario,
  layout: ScenarioLayout,
  viewBox: ViewBoxState,
  localSize: { width: number; height: number },
  scale: number,
) {
  const size = {
    width: localSize.width * scale,
    height: localSize.height * scale,
  };
  const boxes = stationPlatformBoxes(stationId, scenario, layout);
  const visibleViewBox = rectFromViewBox(viewBox);
  if (boxes.length >= 2) {
    const pair = farthestBoxPair(boxes);
    const clippedPlacement = clippedTwoBoxPlacement(pair, visibleViewBox, size, stationId, scenario, layout, scale);
    return clippedPlacement ?? betweenStationBoxes(pair, size);
  }
  if (boxes.length === 1) return besideSingleStationBox(boxes[0], size, stationId, scenario, layout, visibleViewBox, scale);

  const point = stationAnchor(stationId, layout);
  if (!point) return null;
  return { x: point.x - size.width / 2, y: point.y - size.height - STATION_PLACEMENT_GAP * scale };
}

export function stationPlatformBoxes(stationId: string, scenario: Scenario, layout: ScenarioLayout): PlacementRect[] {
  const nodeById = new Map(scenario.physical_nodes.map((node) => [node.id, node]));
  return scenario.track_segments.flatMap((segment) => {
    if (segment.kind !== "station" || !segment.id.includes("platform")) return [];
    const fromNode = nodeById.get(segment.from_node_id);
    const toNode = nodeById.get(segment.to_node_id);
    if (fromNode?.station_id !== stationId || toNode?.station_id !== stationId) return [];
    const from = layout.nodes[segment.from_node_id];
    const to = layout.nodes[segment.to_node_id];
    if (!from || !to) return [];
    const minX = Math.min(from.x, to.x);
    const minY = Math.min(from.y, to.y);
    const maxX = Math.max(from.x, to.x);
    const maxY = Math.max(from.y, to.y);
    return [{
      x: minX - STATION_BOX_PADDING,
      y: minY - STATION_BOX_PADDING,
      width: maxX - minX + STATION_BOX_PADDING * 2,
      height: maxY - minY + STATION_BOX_PADDING * 2,
    }];
  });
}

function farthestBoxPair(boxes: PlacementRect[]): [PlacementRect, PlacementRect] {
  let best: [PlacementRect, PlacementRect] = [boxes[0], boxes[1]];
  let bestDistance = -1;
  for (let leftIndex = 0; leftIndex < boxes.length; leftIndex += 1) {
    for (let rightIndex = leftIndex + 1; rightIndex < boxes.length; rightIndex += 1) {
      const leftCenter = rectCenter(boxes[leftIndex]);
      const rightCenter = rectCenter(boxes[rightIndex]);
      const distance = Math.hypot(leftCenter.x - rightCenter.x, leftCenter.y - rightCenter.y);
      if (distance > bestDistance) {
        bestDistance = distance;
        best = [boxes[leftIndex], boxes[rightIndex]];
      }
    }
  }
  return best;
}

function betweenStationBoxes([first, second]: [PlacementRect, PlacementRect], size: { width: number; height: number }) {
  const firstCenter = rectCenter(first);
  const secondCenter = rectCenter(second);
  const verticalGap = Math.abs(firstCenter.y - secondCenter.y) >= Math.abs(firstCenter.x - secondCenter.x);
  if (verticalGap) {
    const top = firstCenter.y <= secondCenter.y ? first : second;
    const bottom = top === first ? second : first;
    return centeredAt(
      {
        x: (rectCenter(top).x + rectCenter(bottom).x) / 2,
        y: (top.y + top.height + bottom.y) / 2,
      },
      size,
    );
  }

  const left = firstCenter.x <= secondCenter.x ? first : second;
  const right = left === first ? second : first;
  return centeredAt(
    {
      x: (left.x + left.width + right.x) / 2,
      y: (rectCenter(left).y + rectCenter(right).y) / 2,
    },
    size,
  );
}

function clippedTwoBoxPlacement(
  pair: [PlacementRect, PlacementRect],
  viewBox: PlacementRect,
  size: { width: number; height: number },
  stationId: string,
  scenario: Scenario,
  layout: ScenarioLayout,
  scale: number,
) {
  const [first, second] = pair;
  const firstVisibility = visibleAreaRatio(first, viewBox);
  const secondVisibility = visibleAreaRatio(second, viewBox);
  const fullyVisible = firstVisibility === 1 && secondVisibility === 1;
  const bothInvisible = firstVisibility === 0 && secondVisibility === 0;
  const tied = firstVisibility === secondVisibility;
  if (fullyVisible || bothInvisible || tied) return null;

  const visibleBox = firstVisibility > secondVisibility ? first : second;
  return besideSingleStationBox(visibleBox, size, stationId, scenario, layout, viewBox, scale);
}

function besideSingleStationBox(
  box: PlacementRect,
  size: { width: number; height: number },
  stationId: string,
  scenario: Scenario,
  layout: ScenarioLayout,
  viewBox: PlacementRect,
  scale: number,
) {
  const gap = STATION_PLACEMENT_GAP * scale;
  const center = rectCenter(box);
  const candidates = [
    { side: "left", rect: { x: box.x - gap - size.width, y: center.y - size.height / 2, width: size.width, height: size.height } },
    { side: "right", rect: { x: box.x + box.width + gap, y: center.y - size.height / 2, width: size.width, height: size.height } },
    { side: "top", rect: { x: center.x - size.width / 2, y: box.y - gap - size.height, width: size.width, height: size.height } },
    { side: "bottom", rect: { x: center.x - size.width / 2, y: box.y + box.height + gap, width: size.width, height: size.height } },
  ];
  const obstacles = stationPlacementObstacles(stationId, scenario, layout);

  const best = candidates.reduce((bestCandidate, candidate) => {
    const score = stationPlacementCandidateScore(candidate.rect, obstacles, viewBox);
    const bestScore = stationPlacementCandidateScore(bestCandidate.rect, obstacles, viewBox);
    if (score !== bestScore) return score > bestScore ? candidate : bestCandidate;
    return sidePreference(candidate.side) < sidePreference(bestCandidate.side) ? candidate : bestCandidate;
  }, candidates[0]);

  return { x: best.rect.x, y: best.rect.y };
}

function stationPlacementObstacles(stationId: string, scenario: Scenario, layout: ScenarioLayout) {
  const ownPlatformSegmentIds = new Set(
    scenario.track_segments
      .filter((segment) => segment.kind === "station" && segment.id.includes("platform") && segment.id.startsWith(`${stationId}_`))
      .map((segment) => segment.id),
  );
  const nodes = scenario.physical_nodes.flatMap((node) => {
    const point = layout.nodes[node.id];
    return point ? [{ point, radius: STATION_NODE_RADIUS }] : [];
  });
  const segments = scenario.track_segments.flatMap((segment) => {
    if (ownPlatformSegmentIds.has(segment.id)) return [];
    return segmentSamplePoints(segment, layout);
  });
  const stationBoxes = scenario.stations.flatMap((station) => (station.id === stationId ? [] : stationPlatformBoxes(station.id, scenario, layout)));
  return { nodes, segments, stationBoxes };
}

function stationPlacementCandidateScore(
  rect: PlacementRect,
  obstacles: {
    nodes: { point: { x: number; y: number }; radius: number }[];
    segments: { x: number; y: number }[];
    stationBoxes: PlacementRect[];
  },
  viewBox: PlacementRect,
) {
  let clearance = Number.POSITIVE_INFINITY;
  for (const node of obstacles.nodes) {
    clearance = Math.min(clearance, rectClearanceToPoint(rect, node.point) - node.radius);
  }
  for (const point of obstacles.segments) {
    clearance = Math.min(clearance, rectClearanceToPoint(rect, point));
  }
  for (const box of obstacles.stationBoxes) {
    clearance = Math.min(clearance, rectClearanceToRect(rect, box));
  }
  if (!rectContainsRect(viewBox, rect)) clearance -= 10000;
  return clearance;
}

function segmentSamplePoints(segment: TrackSegment, layout: ScenarioLayout) {
  const sampleCount = 8;
  const points: { x: number; y: number }[] = [];
  for (let index = 0; index <= sampleCount; index += 1) {
    const point = pointOnSegment(segment, layout, index / sampleCount);
    if (point) points.push(point);
  }
  return points;
}

function rectClearanceToPoint(rect: PlacementRect, point: { x: number; y: number }) {
  const dx = Math.max(rect.x - point.x, 0, point.x - (rect.x + rect.width));
  const dy = Math.max(rect.y - point.y, 0, point.y - (rect.y + rect.height));
  return Math.hypot(dx, dy);
}

function rectClearanceToRect(left: PlacementRect, right: PlacementRect) {
  const dx = Math.max(right.x - (left.x + left.width), left.x - (right.x + right.width), 0);
  const dy = Math.max(right.y - (left.y + left.height), left.y - (right.y + right.height), 0);
  return Math.hypot(dx, dy);
}

function rectContainsRect(container: PlacementRect, rect: PlacementRect) {
  return rect.x >= container.x && rect.y >= container.y && rect.x + rect.width <= container.x + container.width && rect.y + rect.height <= container.y + container.height;
}

function visibleAreaRatio(rect: PlacementRect, viewBox: PlacementRect) {
  const intersectionWidth = Math.max(0, Math.min(rect.x + rect.width, viewBox.x + viewBox.width) - Math.max(rect.x, viewBox.x));
  const intersectionHeight = Math.max(0, Math.min(rect.y + rect.height, viewBox.y + viewBox.height) - Math.max(rect.y, viewBox.y));
  return (intersectionWidth * intersectionHeight) / (rect.width * rect.height);
}

function rectCenter(rect: PlacementRect) {
  return {
    x: rect.x + rect.width / 2,
    y: rect.y + rect.height / 2,
  };
}

function centeredAt(point: { x: number; y: number }, size: { width: number; height: number }) {
  return {
    x: point.x - size.width / 2,
    y: point.y - size.height / 2,
  };
}

function rectFromViewBox(value: ViewBoxState): PlacementRect {
  return value;
}

function sidePreference(side: string) {
  return ["left", "right", "top", "bottom"].indexOf(side);
}

function stationAnchor(stationId: string, layout: ScenarioLayout) {
  return (
    layout.nodes[`${stationId}_platform_exit`] ??
    layout.nodes[`${stationId}_platform_entry_lr`] ??
    layout.nodes[`${stationId}_platform_exit_lr`] ??
    layout.nodes[`${stationId}_platform_entry`] ??
    layout.nodes[`${stationId}_platform_entry_rl`] ??
    null
  );
}
