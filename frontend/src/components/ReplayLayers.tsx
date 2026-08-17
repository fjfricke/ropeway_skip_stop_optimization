import type { ScenarioLayout } from "../scenarioLayout";
import type { DiscreteScenario, Scenario } from "../types";
import { discreteNodePoint, round } from "./networkGeometry";
import type { ReplayCabinMarker, ReplayCollisionMarker, ReplayStationQueueMarker, ViewBoxState } from "./networkTypes";
import { stationContentPlacement } from "./stationPlacement";
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
        const point = stationContentPlacement(queue.stationId, scenario, layout, viewBox, size, inverseZoom);
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

const STATION_QUEUE_ROW_HEIGHT = 14;
const STATION_QUEUE_LABEL_HEIGHT = 16;
const STATION_QUEUE_ROW_TOP = 22;

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
          <title>{collision.message ?? `Cabin spacing violation: C${collision.cabinIds.join(", C")} · ${collision.distanceM.toFixed(2)}m`}</title>
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
