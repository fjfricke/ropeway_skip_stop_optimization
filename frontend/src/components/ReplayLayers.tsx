import type { ScenarioLayout } from "../scenarioLayout";
import type { DiscreteScenario, Scenario, TrackSegment } from "../types";
import { discreteNodePoint, pointOnSegment, round } from "./networkGeometry";
import type { ReplayCabinMarker, ReplayCollisionMarker, ReplayStationQueueMarker, ViewBoxState } from "./networkTypes";
import { stationVisualColor } from "./stationColors";

export function ReplayStationQueueLayer({
  queues,
  scenario,
  layout,
  viewBox,
  inverseZoom,
}: {
  queues: ReplayStationQueueMarker[];
  scenario: Scenario;
  layout: ScenarioLayout;
  viewBox: ViewBoxState;
  inverseZoom: number;
}) {
  const maxQueue = Math.max(1, ...queues.map((queue) => queue.totalCount));
  return (
    <g className="layer layer--replay-queues">
      {queues.map((queue) => {
        const size = stationQueueSize(queue, maxQueue);
        const point = stationQueuePlacement(queue.stationId, scenario, layout, viewBox, size, inverseZoom);
        if (!point) return null;
        return (
          <g className="station-queue" key={queue.stationId} transform={`translate(${point.x} ${point.y}) scale(${inverseZoom})`}>
            <text className="station-queue__label" x="0" y="12">
              {queue.totalCount} waiting
            </text>
            {queue.destinationQueues.map((item, index) => {
              const width = 18 + (item.count / maxQueue) * 54;
              return (
                <g key={item.destination} transform={`translate(0 ${22 + index * STATION_QUEUE_ROW_HEIGHT})`}>
                  <rect className="station-queue__bar" width={width} height="9" rx="2" fill={stationVisualColor(item.destination, scenario.stations).base} />
                  <text x={width + 5} y="8">
                    {item.destination}:{item.count}
                  </text>
                </g>
              );
            })}
          </g>
        );
      })}
    </g>
  );
}

export type ReplayLayerRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

const STATION_QUEUE_ROW_HEIGHT = 14;
const STATION_QUEUE_LABEL_HEIGHT = 16;
const STATION_QUEUE_ROW_TOP = 22;
const STATION_QUEUE_GAP = 18;
const STATION_BOX_PADDING = 18;
const STATION_NODE_RADIUS = 12;

export function stationQueueSize(queue: ReplayStationQueueMarker, maxQueue: number) {
  const labelWidth = `${queue.totalCount} waiting`.length * 7.4;
  const rowWidth = queue.destinationQueues.reduce((width, item) => {
    const barWidth = 18 + (item.count / maxQueue) * 54;
    const textWidth = `${item.destination}:${item.count}`.length * 6.2;
    return Math.max(width, barWidth + 5 + textWidth);
  }, 0);
  return {
    width: Math.ceil(Math.max(labelWidth, rowWidth)),
    height: STATION_QUEUE_ROW_TOP + Math.max(1, queue.destinationQueues.length) * STATION_QUEUE_ROW_HEIGHT,
  };
}

export function stationQueuePlacement(
  stationId: string,
  scenario: Scenario,
  layout: ScenarioLayout,
  viewBox: ViewBoxState,
  localSize: { width: number; height: number },
  inverseZoom: number,
) {
  const size = {
    width: localSize.width * inverseZoom,
    height: localSize.height * inverseZoom,
  };
  const boxes = stationPlatformBoxes(stationId, scenario, layout);
  const visibleViewBox = rectFromViewBox(viewBox);
  if (boxes.length >= 2) {
    const pair = farthestBoxPair(boxes);
    const clippedPlacement = clippedTwoBoxPlacement(pair, visibleViewBox, size, stationId, scenario, layout, inverseZoom);
    return clippedPlacement ?? betweenStationBoxes(pair, size);
  }
  if (boxes.length === 1) return besideSingleStationBox(boxes[0], size, stationId, scenario, layout, visibleViewBox, inverseZoom);

  const point = stationAnchor(stationId, layout);
  if (!point) return null;
  return { x: point.x - size.width / 2, y: point.y - size.height - STATION_QUEUE_GAP * inverseZoom };
}

function stationPlatformBoxes(stationId: string, scenario: Scenario, layout: ScenarioLayout): ReplayLayerRect[] {
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

function farthestBoxPair(boxes: ReplayLayerRect[]): [ReplayLayerRect, ReplayLayerRect] {
  let best: [ReplayLayerRect, ReplayLayerRect] = [boxes[0], boxes[1]];
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

function betweenStationBoxes([first, second]: [ReplayLayerRect, ReplayLayerRect], size: { width: number; height: number }) {
  const firstCenter = rectCenter(first);
  const secondCenter = rectCenter(second);
  const verticalGap = Math.abs(firstCenter.y - secondCenter.y) >= Math.abs(firstCenter.x - secondCenter.x);
  if (verticalGap) {
    const top = firstCenter.y <= secondCenter.y ? first : second;
    const bottom = top === first ? second : first;
    const center = {
      x: (rectCenter(top).x + rectCenter(bottom).x) / 2,
      y: (top.y + top.height + bottom.y) / 2,
    };
    return centeredAt(center, size);
  }

  const left = firstCenter.x <= secondCenter.x ? first : second;
  const right = left === first ? second : first;
  const center = {
    x: (left.x + left.width + right.x) / 2,
    y: (rectCenter(left).y + rectCenter(right).y) / 2,
  };
  return centeredAt(center, size);
}

function clippedTwoBoxPlacement(
  pair: [ReplayLayerRect, ReplayLayerRect],
  viewBox: ReplayLayerRect,
  size: { width: number; height: number },
  stationId: string,
  scenario: Scenario,
  layout: ScenarioLayout,
  inverseZoom: number,
) {
  const [first, second] = pair;
  const firstVisibility = visibleAreaRatio(first, viewBox);
  const secondVisibility = visibleAreaRatio(second, viewBox);
  const fullyVisible = firstVisibility === 1 && secondVisibility === 1;
  const bothInvisible = firstVisibility === 0 && secondVisibility === 0;
  const tied = firstVisibility === secondVisibility;
  if (fullyVisible || bothInvisible || tied) return null;

  const visibleBox = firstVisibility > secondVisibility ? first : second;
  return besideSingleStationBox(visibleBox, size, stationId, scenario, layout, viewBox, inverseZoom);
}

function besideSingleStationBox(
  box: ReplayLayerRect,
  size: { width: number; height: number },
  stationId: string,
  scenario: Scenario,
  layout: ScenarioLayout,
  viewBox: ReplayLayerRect,
  inverseZoom: number,
) {
  const gap = STATION_QUEUE_GAP * inverseZoom;
  const center = rectCenter(box);
  const candidates = [
    { side: "left", rect: { x: box.x - gap - size.width, y: center.y - size.height / 2, width: size.width, height: size.height } },
    { side: "right", rect: { x: box.x + box.width + gap, y: center.y - size.height / 2, width: size.width, height: size.height } },
    { side: "top", rect: { x: center.x - size.width / 2, y: box.y - gap - size.height, width: size.width, height: size.height } },
    { side: "bottom", rect: { x: center.x - size.width / 2, y: box.y + box.height + gap, width: size.width, height: size.height } },
  ];
  const obstacles = stationQueueObstacles(stationId, scenario, layout);

  const best = candidates.reduce((bestCandidate, candidate) => {
    const score = stationQueueCandidateScore(candidate.rect, obstacles, viewBox);
    const bestScore = stationQueueCandidateScore(bestCandidate.rect, obstacles, viewBox);
    if (score !== bestScore) return score > bestScore ? candidate : bestCandidate;
    return sidePreference(candidate.side) < sidePreference(bestCandidate.side) ? candidate : bestCandidate;
  }, candidates[0]);

  return { x: best.rect.x, y: best.rect.y };
}

function stationQueueObstacles(stationId: string, scenario: Scenario, layout: ScenarioLayout) {
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

function stationQueueCandidateScore(
  rect: ReplayLayerRect,
  obstacles: {
    nodes: { point: { x: number; y: number }; radius: number }[];
    segments: { x: number; y: number }[];
    stationBoxes: ReplayLayerRect[];
  },
  viewBox: ReplayLayerRect,
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

function rectClearanceToPoint(rect: ReplayLayerRect, point: { x: number; y: number }) {
  const dx = Math.max(rect.x - point.x, 0, point.x - (rect.x + rect.width));
  const dy = Math.max(rect.y - point.y, 0, point.y - (rect.y + rect.height));
  return Math.hypot(dx, dy);
}

function rectClearanceToRect(left: ReplayLayerRect, right: ReplayLayerRect) {
  const dx = Math.max(right.x - (left.x + left.width), left.x - (right.x + right.width), 0);
  const dy = Math.max(right.y - (left.y + left.height), left.y - (right.y + right.height), 0);
  return Math.hypot(dx, dy);
}

function rectContainsRect(container: ReplayLayerRect, rect: ReplayLayerRect) {
  return rect.x >= container.x && rect.y >= container.y && rect.x + rect.width <= container.x + container.width && rect.y + rect.height <= container.y + container.height;
}

function visibleAreaRatio(rect: ReplayLayerRect, viewBox: ReplayLayerRect) {
  const intersectionWidth = Math.max(0, Math.min(rect.x + rect.width, viewBox.x + viewBox.width) - Math.max(rect.x, viewBox.x));
  const intersectionHeight = Math.max(0, Math.min(rect.y + rect.height, viewBox.y + viewBox.height) - Math.max(rect.y, viewBox.y));
  return (intersectionWidth * intersectionHeight) / (rect.width * rect.height);
}

function rectCenter(rect: ReplayLayerRect) {
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

function rectFromViewBox(value: ViewBoxState): ReplayLayerRect {
  return value;
}

function sidePreference(side: string) {
  return ["left", "right", "top", "bottom"].indexOf(side);
}

export function ReplayCabinLayer({
  cabins,
  discreteScenario,
  scenario,
  layout,
  inverseZoom,
  selectedCabinId,
  showFill = true,
  onCabinSelect,
}: {
  cabins: ReplayCabinMarker[];
  discreteScenario: DiscreteScenario | null;
  scenario: Scenario;
  layout: ScenarioLayout;
  inverseZoom: number;
  selectedCabinId: number | null;
  showFill?: boolean;
  onCabinSelect?: (cabinId: number) => void;
}) {
  const segmentById = new Map(scenario.track_segments.map((segment) => [segment.id, segment]));
  const nodeById = new Map((discreteScenario?.nodes ?? []).map((node) => [node.id, node]));

  return (
    <g className="layer layer--replay-cabins">
      {cabins.map((cabin, index) => {
        const node = nodeById.get(cabin.nodeId);
        const point = cabin.x !== undefined && cabin.y !== undefined
          ? { x: cabin.x, y: cabin.y }
          : node
            ? discreteNodePoint(node, layout, segmentById)
            : layout.nodes[cabin.nodeId] ?? null;
        if (!point) return null;
        const selected = selectedCabinId === cabin.cabinId;
        const capacity = cabin.capacity ?? 0;
        const loadCount = cabin.loadCount ?? 0;
        const radius = selected ? 12 : 10;
        return (
          <g
            key={cabin.cabinId}
            className={`replay-cabin replay-cabin--${index % 6} ${loadCount > 0 ? "has-load" : ""} ${selected ? "is-selected" : ""}`}
            transform={`translate(${point.x} ${point.y}) scale(${inverseZoom})`}
            onClick={(event) => {
              event.stopPropagation();
              onCabinSelect?.(cabin.cabinId);
            }}
          >
            <circle className="replay-cabin__shell" r={radius} />
            <circle className="replay-cabin__empty" r={radius - 2.2} />
            {showFill && capacity > 0 ? (
              <g className="replay-cabin__pie">
                {cabinPieSlices(cabin.destinationLoads ?? [], capacity, radius - 2.2).map((slice) => (
                  <path key={slice.key} className="replay-cabin__slice" d={slice.d} fill={stationVisualColor(slice.destination, scenario.stations).base} />
                ))}
              </g>
            ) : null}
            <text x="0" y="3">
              C{cabin.cabinId}
            </text>
            <title>C{cabin.cabinId}: {loadCount}/{capacity || "?"} passengers · {cabin.nodeId}</title>
          </g>
        );
      })}
    </g>
  );
}

export function ReplayCollisionLayer({
  collisions,
  inverseZoom,
}: {
  collisions: ReplayCollisionMarker[];
  inverseZoom: number;
}) {
  if (collisions.length === 0) return null;
  return (
    <g className="layer layer--replay-collisions" aria-label="Replay collision warnings">
      {collisions.map((collision) => (
        <g key={collision.id} className="replay-collision-marker" transform={`translate(${collision.x} ${collision.y}) scale(${inverseZoom})`}>
          <circle r="17" />
          <text x="0" y="2" dominantBaseline="central">
            !
          </text>
          <title>
            Cabin spacing violation: C{collision.cabinIds.join(", C")} · {collision.distanceM.toFixed(2)}m
          </title>
        </g>
      ))}
    </g>
  );
}

function cabinPieSlices(destinationLoads: { destination: string; count: number }[], capacity: number, radius: number) {
  if (capacity <= 0) return [];
  let cursor = -90;
  return destinationLoads.flatMap((item, index) => {
    if (item.count <= 0) return [];
    const sliceDegrees = Math.min(360, (item.count / capacity) * 360);
    const start = cursor;
    const end = cursor + sliceDegrees;
    cursor = end;
    return [{
      key: `${item.destination}-${index}`,
      destination: item.destination,
      d: sliceDegrees >= 359.999 ? fullCirclePath(radius) : pieSlicePath(radius, start, end),
    }];
  });
}

function pieSlicePath(radius: number, startDeg: number, endDeg: number) {
  const start = polarPoint(radius, startDeg);
  const end = polarPoint(radius, endDeg);
  const largeArc = endDeg - startDeg > 180 ? 1 : 0;
  return [
    "M 0 0",
    `L ${round(start.x)} ${round(start.y)}`,
    `A ${radius} ${radius} 0 ${largeArc} 1 ${round(end.x)} ${round(end.y)}`,
    "Z",
  ].join(" ");
}

function fullCirclePath(radius: number) {
  return [
    `M 0 ${-radius}`,
    `A ${radius} ${radius} 0 1 1 0 ${radius}`,
    `A ${radius} ${radius} 0 1 1 0 ${-radius}`,
    "Z",
  ].join(" ");
}

function polarPoint(radius: number, degrees: number) {
  const radians = (degrees * Math.PI) / 180;
  return {
    x: radius * Math.cos(radians),
    y: radius * Math.sin(radians),
  };
}

function stationQueueAnchor(stationId: string, layout: ScenarioLayout) {
  const point = stationAnchor(stationId, layout);
  if (!point) return null;
  return { x: point.x - 36, y: point.y - 64 };
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
