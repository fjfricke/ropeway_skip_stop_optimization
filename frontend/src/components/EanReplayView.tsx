import { CircleAlert, FastForward, Pause, Play, RotateCcw, RotateCw, SkipBack, SkipForward, Waypoints } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { layoutForScenario } from "../scenarioLayout";
import type { LayoutPoint, ScenarioLayout } from "../scenarioLayout";
import type {
  EanPassengerServicePlan,
  EanPassengerServiceResult,
  EanPhysicalEvent,
  EanPhysicalReplay,
  EanServedRideGroup,
  Scenario,
  SpeedProfile,
  TrackSegment,
} from "../types";
import { DemandSummaryPanel, type DemandSummaryRow } from "./DemandSummaryPanel";
import { NetworkSvg, type ReplayCabinMarker, type ReplayCollisionMarker } from "./NetworkSvg";
import type { ReplayStationQueueMarker } from "./NetworkSvg";
import { useNetworkPanelContentHeight } from "./useNetworkPanelContentHeight";
import type { ArcColorMode, DiscreteViewerToggles, ViewerToggles } from "./viewerTypes";

interface EanReplayViewProps {
  scenario: Scenario;
  eanReplay: EanPhysicalReplay | null;
  eanPassengerService: EanPassengerServiceResult | null;
  eanReplayWarning: string | null;
  eanPassengerServiceWarning: string | null;
  toggles: ViewerToggles;
  arcColorMode: ArcColorMode;
  onExportClick?: (timeSeconds: number) => void;
}

export interface EanPassengerEvent {
  kind: "boarding" | "alighting";
  ride: EanServedRideGroup;
  timeSeconds: number;
  origin: string;
  destination: string;
}

export interface EanPassengerState {
  cabinLoadsById: Map<number, { loadCount: number; destinationLoads: { destination: string; count: number }[] }>;
  queueMarkers: ReplayStationQueueMarker[];
  demandRows: DemandSummaryRow[];
  currentEvents: EanPassengerEvent[];
  waitingCount: number;
  onboardCount: number;
}

type EanCabinPosition = {
  nodeId: string;
  x: number;
  y: number;
  physicalNodeId?: string | null;
  segmentId?: string | null;
  positionM?: number | null;
  fromNodeId?: string | null;
  toNodeId?: string | null;
  segmentLengthM?: number | null;
  resourceId?: string | null;
};

export type PlaybackDirection = -1 | 1;

const REPLAY_DISCRETE_TOGGLES: DiscreteViewerToggles = {
  enabled: false,
  showMoveArcs: false,
  showWaitArcs: false,
  showOwnSegmentHeadway: false,
  showAdjacentSegmentHeadway: false,
  showMultiSegmentHeadway: false,
};

export const SPEED_OPTIONS = [1, 2, 5, 10];
export const MANUAL_STEP_SECONDS = 0.5;
const SLIDER_STEP_SECONDS = 0.1;
export const EVENT_TOLERANCE_SECONDS = 0.25;
const HEADWAY_WARNING_EPSILON_M = 1e-6;

export function EanReplayView({
  scenario,
  eanReplay,
  eanPassengerService,
  eanReplayWarning,
  eanPassengerServiceWarning,
  toggles,
  arcColorMode,
  onExportClick,
}: EanReplayViewProps) {
  const networkPanelRef = useRef<HTMLDivElement | null>(null);
  const sidePanelMaxHeight = useNetworkPanelContentHeight(networkPanelRef);
  const layout = useMemo(() => layoutForScenario(scenario), [scenario]);
  const [timeSeconds, setTimeSeconds] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const [playbackDirection, setPlaybackDirection] = useState<PlaybackDirection>(1);
  const [selectedCabinId, setSelectedCabinId] = useState<number | null>(eanReplay?.events[0]?.cabin_id ?? null);

  const timeBounds = useMemo(() => eanReplayTimeBounds(eanReplay), [eanReplay]);
  const eventsByCabin = useMemo(() => groupEventsByCabin(eanReplay?.events ?? []), [eanReplay]);
  const passengerPlan = eanPassengerService?.passenger_plan ?? null;
  const passengerState = useMemo(
    () => buildEanPassengerState(scenario, passengerPlan, timeSeconds, EVENT_TOLERANCE_SECONDS),
    [passengerPlan, scenario, timeSeconds],
  );
  const markers = useMemo(
    () => eanCabinMarkersAtTime(scenario, layout, eventsByCabin, timeSeconds, passengerState.cabinLoadsById),
    [eventsByCabin, layout, passengerState.cabinLoadsById, scenario, timeSeconds],
  );
  const collisionMarkers = useMemo(() => eanReplayCollisionMarkers(scenario, markers), [markers, scenario]);
  const selectedMarker = markers.find((marker) => marker.cabinId === selectedCabinId) ?? markers[0] ?? null;
  const selectedEvent = selectedMarker ? latestEventAtOrBefore(eventsByCabin.get(selectedMarker.cabinId) ?? [], timeSeconds) : null;
  const currentEvents = useMemo(
    () => (eanReplay ? eventsNearTime(eanReplay.events, timeSeconds, EVENT_TOLERANCE_SECONDS) : []),
    [eanReplay, timeSeconds],
  );

  useEffect(() => {
    setTimeSeconds((current) => clamp(current, timeBounds.min, timeBounds.max));
  }, [timeBounds]);

  useEffect(() => {
    setSelectedCabinId((current) => current ?? eanReplay?.events[0]?.cabin_id ?? null);
  }, [eanReplay]);

  useEffect(() => {
    if (!isPlaying || !eanReplay) return;
    let frameId = 0;
    let previousFrameMs: number | null = null;
    const animate = (frameMs: number) => {
      if (previousFrameMs !== null) {
        const elapsedSeconds = (frameMs - previousFrameMs) / 1000;
        setTimeSeconds((current) => {
          const next = advanceReplayTime(current, elapsedSeconds * playbackSpeed * playbackDirection, timeBounds.min, timeBounds.max);
          if (isReplayBoundary(next, playbackDirection, timeBounds.min, timeBounds.max)) setIsPlaying(false);
          return next;
        });
      }
      previousFrameMs = frameMs;
      frameId = window.requestAnimationFrame(animate);
    };
    frameId = window.requestAnimationFrame(animate);
    return () => window.cancelAnimationFrame(frameId);
  }, [eanReplay, isPlaying, playbackDirection, playbackSpeed, timeBounds.max, timeBounds.min]);

  if (!eanReplay) {
    return (
      <section className="replay-empty">
        <CircleAlert size={18} />
        <strong>{eanReplayWarning ?? "EAN replay unavailable"}</strong>
      </section>
    );
  }

  return (
    <section className="replay-view">
      <div className="network-panel replay-network" ref={networkPanelRef}>
        <div className="network-panel__header">
          <div>
            <h2>EAN Cabin Replay</h2>
            <p>Continuous physical replay interpolated between EAN events</p>
          </div>
          <div className="status-pill">
            <FastForward size={16} />
            {markers.length} cabins · {eanReplay.events.length} events
          </div>
        </div>
        <NetworkSvg
          scenario={scenario}
          discreteScenario={null}
          layout={layout}
          selected={null}
          hovered={null}
          toggles={toggles}
          arcColorMode={arcColorMode}
          discreteMode="selected"
          discreteToggles={REPLAY_DISCRETE_TOGGLES}
          replayCabins={markers}
          replayCollisionMarkers={collisionMarkers}
          replayStationQueues={passengerState.queueMarkers}
          selectedCabinId={selectedMarker?.cabinId ?? selectedCabinId}
          onExportClick={onExportClick ? () => onExportClick(timeSeconds) : undefined}
          onSelect={() => undefined}
          onHover={() => undefined}
          onCabinSelect={setSelectedCabinId}
        />
      </div>

      <aside className="side-panel replay-side" style={sidePanelMaxHeight === null ? undefined : { maxHeight: sidePanelMaxHeight }}>
        <section className="panel replay-controls">
          <header className="panel__header">
            <Play size={17} />
            <h2>Timeline</h2>
          </header>
          <div className="replay-buttons">
            <button
              onClick={() => {
                setIsPlaying(false);
                setTimeSeconds((current) => Math.max(timeBounds.min, current - MANUAL_STEP_SECONDS));
              }}
              aria-label="Previous time"
            >
              <SkipBack size={16} />
            </button>
            <button
              className="replay-play"
              onClick={() => {
                if (isPlaying) {
                  setIsPlaying(false);
                  return;
                }
                setTimeSeconds((current) => replayStartTimeForDirection(current, playbackDirection, timeBounds.min, timeBounds.max));
                setIsPlaying(true);
              }}
            >
              {isPlaying ? <Pause size={16} /> : <Play size={16} />}
              {isPlaying ? "Pause" : "Play"}
            </button>
            <button
              onClick={() => {
                setIsPlaying(false);
                setTimeSeconds((current) => Math.min(timeBounds.max, current + MANUAL_STEP_SECONDS));
              }}
              aria-label="Next time"
            >
              <SkipForward size={16} />
            </button>
            <button
              className="replay-direction"
              onClick={() => setPlaybackDirection((current) => (current === 1 ? -1 : 1))}
              aria-label={playbackDirection === 1 ? "Playback direction forward" : "Playback direction backward"}
              title={playbackDirection === 1 ? "Forward playback" : "Backward playback"}
            >
              {playbackDirection === 1 ? <RotateCw size={17} /> : <RotateCcw size={17} />}
            </button>
          </div>
          <input
            aria-label="EAN replay time"
            className="replay-slider"
            type="range"
            min={timeBounds.min}
            max={timeBounds.max}
            step={SLIDER_STEP_SECONDS}
            value={timeSeconds}
            onChange={(event) => setTimeSeconds(Number(event.target.value))}
          />
          <div className="replay-time">
            <strong>{formatSeconds(timeSeconds)}</strong>
            <span>/ {formatSeconds(timeBounds.max)}</span>
            <span>{clockLabel(scenario.service_start_time, timeSeconds)}</span>
          </div>
          <div className="speed-buttons" aria-label="Playback speed">
            {SPEED_OPTIONS.map((speed) => (
              <button
                key={speed}
                className={playbackSpeed === speed ? "is-active" : ""}
                onClick={() => setPlaybackSpeed(speed)}
              >
                {speed}x
              </button>
            ))}
          </div>
        </section>

        {passengerPlan ? (
          <DemandSummaryPanel
            title="Waiting Passengers"
            total={passengerState.waitingCount}
            rows={passengerState.demandRows}
            emptyMessage="No waiting passengers"
            className="replay-demand-panel"
          >
            <EanPassengerEventList events={passengerState.currentEvents} />
          </DemandSummaryPanel>
        ) : null}

        <section className="panel">
          <header className="panel__header">
            <Waypoints size={17} />
            <h2>Events At Time</h2>
            <span className="panel__count">{currentEvents.length}</span>
          </header>
          {currentEvents.length > 0 ? (
            <div className="ean-event-list">
              {currentEvents.map((event) => (
                <button
                  className={event.cabin_id === selectedCabinId ? "ean-event is-active" : "ean-event"}
                  key={eventKey(event)}
                  onClick={() => setSelectedCabinId(event.cabin_id)}
                >
                  <span>{formatSeconds(event.time_seconds)}</span>
                  <strong>C{event.cabin_id}</strong>
                  <em>{event.event_kind}</em>
                  <small>{event.physical_node_id}</small>
                </button>
              ))}
            </div>
          ) : (
            <div className="empty-panel empty-panel--compact">No event at this instant</div>
          )}
        </section>

        <section className="panel">
          <header className="panel__header">
            <FastForward size={17} />
            <h2>Cabin Inspector</h2>
          </header>
          {selectedMarker ? (
            <div className="kv-list">
              <h3>C{selectedMarker.cabinId}</h3>
              <div className="kv-row">
                <span>time</span>
                <strong>{formatSeconds(timeSeconds)}</strong>
              </div>
              <div className="kv-row">
                <span>position</span>
                <strong>{selectedMarker.nodeId}</strong>
              </div>
              <div className="kv-row">
                <span>event</span>
                <strong>{selectedEvent?.event_kind ?? "between events"}</strong>
              </div>
              <div className="kv-row">
                <span>station</span>
                <strong>{selectedEvent?.station_id ?? "n/a"}</strong>
              </div>
              <div className="kv-row">
                <span>switch</span>
                <strong>{selectedEvent?.switch_id ?? "n/a"}</strong>
              </div>
              <div className="kv-row">
                <span>passengers</span>
                <strong>{formatLoad(selectedMarker.loadCount ?? 0, selectedMarker.capacity ?? scenario.operating.cabin_capacity)}</strong>
              </div>
              {selectedMarker.destinationLoads?.length ? (
                <div className="onboard-list">
                  {selectedMarker.destinationLoads.map((load) => (
                    <div className="onboard-row" key={load.destination}>
                      <span>to {load.destination}</span>
                      <strong>{load.count}</strong>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : (
            <div className="empty-panel">No active cabin</div>
          )}
        </section>

        <section className="panel">
          <header className="panel__header">
            <CircleAlert size={17} />
            <h2>Replay Status</h2>
          </header>
          <div className="metric-grid">
            <div className="metric">
              <span>source</span>
              <strong>EAN</strong>
            </div>
            <div className="metric">
              <span>mode</span>
              <strong>continuous</strong>
            </div>
            <div className="metric">
              <span>served</span>
              <strong>{eanPassengerService?.metadata.served_passenger_count ?? "n/a"}</strong>
            </div>
            <div className="metric">
              <span>onboard</span>
              <strong>{passengerState.onboardCount}</strong>
            </div>
            <div className="metric">
              <span>objective</span>
              <strong>{formatPassengerHours(eanPassengerService?.metadata.objective_passenger_hours)}</strong>
            </div>
            <div className="metric">
              <span>status</span>
              <strong>{eanPassengerService?.metadata.solver_status ?? eanPassengerService?.metadata.status ?? "no passengers"}</strong>
            </div>
            <div className="metric">
              <span>gap</span>
              <strong>{formatPercent(eanPassengerService?.metadata.mip_gap)}</strong>
            </div>
            <div className="metric">
              <span>runtime</span>
              <strong>{formatOptionalSeconds(eanPassengerService?.metadata.runtime_seconds)}</strong>
            </div>
          </div>
          {!passengerPlan ? (
            <p className="panel-note">{eanPassengerServiceWarning ?? "Passenger service result unavailable in this artifact set."}</p>
          ) : null}
        </section>
      </aside>
    </section>
  );
}

export function eanCabinMarkersAtTime(
  scenario: Scenario,
  layout: ScenarioLayout,
  eventsByCabin: Map<number, EanPhysicalEvent[]>,
  timeSeconds: number,
  cabinLoadsById: Map<number, { loadCount: number; destinationLoads: { destination: string; count: number }[] }>,
): ReplayCabinMarker[] {
  return [...eventsByCabin.entries()].flatMap(([cabinId, events]) => {
    const position = eanCabinPositionAtTime(scenario, layout, events, timeSeconds);
    if (!position) return [];
    const load = cabinLoadsById.get(cabinId);
    return [{
      cabinId,
      nodeId: position.nodeId,
      x: position.x,
      y: position.y,
      physicalNodeId: position.physicalNodeId,
      segmentId: position.segmentId,
      positionM: position.positionM,
      fromNodeId: position.fromNodeId,
      toNodeId: position.toNodeId,
      segmentLengthM: position.segmentLengthM,
      resourceId: position.resourceId,
      loadCount: load?.loadCount ?? 0,
      capacity: scenario.operating.cabin_capacity,
      destinationLoads: load?.destinationLoads ?? [],
    }];
  });
}

export function eanReplayCollisionMarkers(scenario: Scenario, markers: ReplayCabinMarker[]): ReplayCollisionMarker[] {
  const requiredSpacingM = scenario.operating.cabin_length_m + scenario.operating.min_clearance_m;
  if (requiredSpacingM <= 0) return [];
  const collisions: ReplayCollisionMarker[] = [];

  for (let leftIndex = 0; leftIndex < markers.length; leftIndex += 1) {
    const left = markers[leftIndex];
    if (left.x === undefined || left.y === undefined) continue;
    for (let rightIndex = leftIndex + 1; rightIndex < markers.length; rightIndex += 1) {
      const right = markers[rightIndex];
      if (right.x === undefined || right.y === undefined) continue;
      const distanceM = cabinSpacingDistanceM(left, right);
      if (distanceM === null || distanceM >= requiredSpacingM - HEADWAY_WARNING_EPSILON_M) continue;
      addCollisionMarker(collisions, {
        id: `collision-${left.cabinId}-${right.cabinId}`,
        x: (left.x + right.x) / 2,
        y: (left.y + right.y) / 2,
        cabinIds: [left.cabinId, right.cabinId],
        distanceM,
      });
    }
  }

  return collisions;
}

function cabinSpacingDistanceM(left: ReplayCabinMarker, right: ReplayCabinMarker) {
  if (left.physicalNodeId && right.physicalNodeId && left.physicalNodeId === right.physicalNodeId) return 0;

  if (hasSegmentPosition(left) && hasSegmentPosition(right)) {
    if (left.segmentId === right.segmentId) return Math.abs(left.positionM - right.positionM);
    if (left.fromNodeId === right.fromNodeId && left.toNodeId === right.toNodeId) return Math.abs(left.positionM - right.positionM);
    if (left.fromNodeId === right.toNodeId && left.toNodeId === right.fromNodeId) {
      return Math.abs(left.positionM - (right.segmentLengthM - right.positionM));
    }

    const sharedNodeIds = [left.fromNodeId, left.toNodeId].filter((nodeId) => nodeId === right.fromNodeId || nodeId === right.toNodeId);
    if (sharedNodeIds.length > 0) {
      return Math.min(...sharedNodeIds.map((nodeId) => distanceToSegmentEndpointM(left, nodeId) + distanceToSegmentEndpointM(right, nodeId)));
    }
  }

  if (left.physicalNodeId && hasSegmentPosition(right)) return distanceToSegmentEndpointM(right, left.physicalNodeId);
  if (right.physicalNodeId && hasSegmentPosition(left)) return distanceToSegmentEndpointM(left, right.physicalNodeId);
  return null;
}

function hasSegmentPosition(marker: ReplayCabinMarker): marker is ReplayCabinMarker & {
  segmentId: string;
  positionM: number;
  fromNodeId: string;
  toNodeId: string;
  segmentLengthM: number;
} {
  return (
    typeof marker.segmentId === "string"
    && typeof marker.positionM === "number"
    && typeof marker.fromNodeId === "string"
    && typeof marker.toNodeId === "string"
    && typeof marker.segmentLengthM === "number"
  );
}

function distanceToSegmentEndpointM(
  marker: ReplayCabinMarker & { positionM: number; fromNodeId: string; toNodeId: string; segmentLengthM: number },
  nodeId: string,
) {
  if (nodeId === marker.fromNodeId) return marker.positionM;
  if (nodeId === marker.toNodeId) return marker.segmentLengthM - marker.positionM;
  return Number.POSITIVE_INFINITY;
}

function addCollisionMarker(collisions: ReplayCollisionMarker[], marker: ReplayCollisionMarker) {
  const existing = collisions.find((collision) => Math.hypot(collision.x - marker.x, collision.y - marker.y) < 16);
  if (!existing) {
    collisions.push(marker);
    return;
  }
  existing.cabinIds = [...new Set([...existing.cabinIds, ...marker.cabinIds])].sort((left, right) => left - right);
  existing.distanceM = Math.min(existing.distanceM, marker.distanceM);
  existing.x = (existing.x + marker.x) / 2;
  existing.y = (existing.y + marker.y) / 2;
}

export function buildEanPassengerState(
  scenario: Scenario,
  passengerPlan: EanPassengerServicePlan | null,
  timeSeconds: number,
  eventToleranceSeconds: number,
): EanPassengerState {
  if (!passengerPlan) {
    return {
      cabinLoadsById: new Map(),
      queueMarkers: [],
      demandRows: [],
      currentEvents: [],
      waitingCount: 0,
      onboardCount: 0,
    };
  }

  const demandByGroupId = new Map(
    scenario.demands.map((demand, index) => [
      `demand::${index}`,
      {
        origin: demand.origin,
        destination: demand.destination,
        count: demand.count,
        releaseTimeSeconds: releaseSeconds(scenario.service_start_time, demand.arrival_time),
      },
    ]),
  );

  const activeLoadsByCabin = new Map<number, Map<string, number>>();
  const boardedByGroupId = new Map<string, number>();
  const currentEvents: EanPassengerEvent[] = [];
  let onboardCount = 0;

  for (const ride of passengerPlan.served_rides) {
    const demand = demandByGroupId.get(ride.demand_group_id);
    if (!demand) continue;
    if (ride.boarding_time_seconds <= timeSeconds) {
      boardedByGroupId.set(ride.demand_group_id, (boardedByGroupId.get(ride.demand_group_id) ?? 0) + ride.count);
    }
    if (ride.boarding_time_seconds <= timeSeconds && timeSeconds < ride.alighting_time_seconds) {
      const destinationLoads = activeLoadsByCabin.get(ride.cabin_id) ?? new Map<string, number>();
      destinationLoads.set(demand.destination, (destinationLoads.get(demand.destination) ?? 0) + ride.count);
      activeLoadsByCabin.set(ride.cabin_id, destinationLoads);
      onboardCount += ride.count;
    }
    if (Math.abs(ride.boarding_time_seconds - timeSeconds) <= eventToleranceSeconds) {
      currentEvents.push({ kind: "boarding", ride, timeSeconds: ride.boarding_time_seconds, origin: demand.origin, destination: demand.destination });
    }
    if (Math.abs(ride.alighting_time_seconds - timeSeconds) <= eventToleranceSeconds) {
      currentEvents.push({ kind: "alighting", ride, timeSeconds: ride.alighting_time_seconds, origin: demand.origin, destination: demand.destination });
    }
  }

  const cabinLoadsById = new Map(
    [...activeLoadsByCabin.entries()].map(([cabinId, destinationMap]) => {
      const destinationLoads = [...destinationMap.entries()]
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([destination, count]) => ({ destination, count }));
      return [cabinId, {
        loadCount: destinationLoads.reduce((sum, load) => sum + load.count, 0),
        destinationLoads,
      }];
    }),
  );

  const queueMarkersByStation = new Map<string, ReplayStationQueueMarker>();
  const demandRows: DemandSummaryRow[] = [];
  let waitingCount = 0;

  for (const [groupId, demand] of demandByGroupId.entries()) {
    if (demand.releaseTimeSeconds > timeSeconds) continue;
    const boarded = boardedByGroupId.get(groupId) ?? 0;
    const waiting = Math.max(0, demand.count - boarded);
    if (waiting <= 0) continue;
    waitingCount += waiting;
    demandRows.push({
      id: groupId,
      origin: demand.origin,
      destination: demand.destination,
      count: waiting,
      detail: `since ${clockLabel(scenario.service_start_time, demand.releaseTimeSeconds)}`,
    });

    const marker = queueMarkersByStation.get(demand.origin) ?? {
      stationId: demand.origin,
      totalCount: 0,
      destinationQueues: [],
    };
    marker.totalCount += waiting;
    marker.destinationQueues.push({ destination: demand.destination, count: waiting });
    queueMarkersByStation.set(demand.origin, marker);
  }

  return {
    cabinLoadsById,
    queueMarkers: [...queueMarkersByStation.values()].map((marker) => ({
      ...marker,
      destinationQueues: marker.destinationQueues.sort((left, right) => left.destination.localeCompare(right.destination)),
    })),
    demandRows: demandRows.sort((left, right) => left.origin.localeCompare(right.origin) || left.destination.localeCompare(right.destination)),
    currentEvents: currentEvents.sort((left, right) => left.timeSeconds - right.timeSeconds || left.kind.localeCompare(right.kind)),
    waitingCount,
    onboardCount,
  };
}

function EanPassengerEventList({ events }: { events: EanPassengerEvent[] }) {
  if (events.length === 0) return null;
  return (
    <div className="passenger-event-list" aria-label="Passenger events at current EAN time">
      {events.map((event, index) => (
        <div
          className={event.kind === "boarding" ? "passenger-event" : "passenger-event passenger-event--alighting"}
          key={`${event.kind}-${event.ride.demand_group_id}-${event.ride.cabin_id}-${event.timeSeconds}-${index}`}
        >
          <span>
            C{event.ride.cabin_id} {event.kind === "boarding" ? "boards" : "unloads"} {event.ride.count} {event.kind === "boarding" ? `to ${event.destination}` : `at ${event.destination}`}
          </span>
          <small>{formatSeconds(event.timeSeconds)}</small>
        </div>
      ))}
    </div>
  );
}

function eanCabinPositionAtTime(
  scenario: Scenario,
  layout: ScenarioLayout,
  events: EanPhysicalEvent[],
  timeSeconds: number,
): EanCabinPosition | null {
  const first = events[0];
  if (!first || timeSeconds < first.time_seconds) return null;

  let previous = first;
  let next: EanPhysicalEvent | null = null;
  for (const event of events) {
    if (event.time_seconds <= timeSeconds) {
      previous = event;
      continue;
    }
    next = event;
    break;
  }

  if (!next) return pointAtNode(layout, previous.physical_node_id);
  if (next.time_seconds <= previous.time_seconds) return pointAtNode(layout, next.physical_node_id);
  if (next.source_segment_ids.length === 0) return pointAtNode(layout, previous.physical_node_id);

  return pointAlongSegmentsAtTime(
    scenario,
    layout,
    next.source_segment_ids,
    timeSeconds - previous.time_seconds,
    next.time_seconds - previous.time_seconds,
  ) ?? pointAtNode(layout, previous.physical_node_id);
}

function pointAlongSegmentsAtTime(
  scenario: Scenario,
  layout: ScenarioLayout,
  segmentIds: string[],
  elapsedSeconds: number,
  eventDurationSeconds: number,
): EanCabinPosition | null {
  const segmentById = new Map(scenario.track_segments.map((segment) => [segment.id, segment]));
  const segments = segmentIds.map((segmentId) => segmentById.get(segmentId)).filter((segment): segment is TrackSegment => segment !== undefined);
  if (segments.length === 0) return null;

  const segmentDurations = segments.map(travelSecondsForSegment);
  const totalTravelSeconds = segmentDurations.reduce((sum, seconds) => sum + seconds, 0);
  const progressRatio = eventDurationSeconds <= 0 ? 1 : clamp(elapsedSeconds / eventDurationSeconds, 0, 1);
  if (totalTravelSeconds <= 0) return pointAlongSegmentsByDistance(layout, segments, progressRatio);

  let targetElapsedSeconds = progressRatio * totalTravelSeconds;

  if (targetElapsedSeconds <= 0) {
    const first = segments[0];
    const point = pointOnSegment(first, layout, 0);
    return point ? positionOnSegment(first, point, 0) : null;
  }

  for (let index = 0; index < segments.length; index += 1) {
    const segment = segments[index];
    const segmentDurationSeconds = segmentDurations[index];
    if (targetElapsedSeconds <= segmentDurationSeconds) {
      const distanceM = travelDistanceAtTime(segment.length_m, segment.speed_profile, targetElapsedSeconds, segmentDurationSeconds);
      const point = pointOnSegment(segment, layout, segment.length_m === 0 ? 1 : distanceM / segment.length_m);
      return point ? positionOnSegment(segment, point, distanceM) : null;
    }
    targetElapsedSeconds -= segmentDurationSeconds;
  }
  const last = segments[segments.length - 1];
  const point = pointOnSegment(last, layout, 1);
  return point ? positionOnSegment(last, point, last.length_m) : null;
}

function pointAlongSegmentsByDistance(
  layout: ScenarioLayout,
  segments: TrackSegment[],
  rawRatio: number,
): EanCabinPosition | null {
  const totalLength = segments.reduce((sum, segment) => sum + segment.length_m, 0);
  let targetDistance = clamp(rawRatio, 0, 1) * totalLength;
  for (const segment of segments) {
    if (targetDistance <= segment.length_m) {
      const point = pointOnSegment(segment, layout, segment.length_m === 0 ? 1 : targetDistance / segment.length_m);
      return point ? positionOnSegment(segment, point, targetDistance) : null;
    }
    targetDistance -= segment.length_m;
  }
  const last = segments[segments.length - 1];
  const point = pointOnSegment(last, layout, 1);
  return point ? positionOnSegment(last, point, last.length_m) : null;
}

function travelSecondsForSegment(segment: TrackSegment) {
  const profile = segment.speed_profile;
  if (!profile || segment.length_m <= 0) return 0;
  if (profile.kind === "constant") {
    const speed = profile.speed_m_per_s ?? 0;
    return speed > 0 ? segment.length_m / speed : 0;
  }
  const startSpeed = profile.start_speed_m_per_s ?? 0;
  const endSpeed = profile.end_speed_m_per_s ?? 0;
  const averageSpeed = (startSpeed + endSpeed) / 2;
  return averageSpeed > 0 ? segment.length_m / averageSpeed : 0;
}

function travelDistanceAtTime(lengthM: number, profile: SpeedProfile | null, elapsedSeconds: number, totalSeconds: number) {
  if (!profile || totalSeconds <= 0) return lengthM;
  if (profile.kind === "constant") {
    return clamp((profile.speed_m_per_s ?? 0) * elapsedSeconds, 0, lengthM);
  }
  const startSpeed = profile.start_speed_m_per_s ?? 0;
  const endSpeed = profile.end_speed_m_per_s ?? 0;
  const acceleration = (endSpeed - startSpeed) / totalSeconds;
  return clamp(startSpeed * elapsedSeconds + 0.5 * acceleration * elapsedSeconds * elapsedSeconds, 0, lengthM);
}

function pointAtNode(layout: ScenarioLayout, nodeId: string) {
  const point = layout.nodes[nodeId];
  return point ? { nodeId, physicalNodeId: nodeId, x: point.x, y: point.y } : null;
}

function positionOnSegment(segment: TrackSegment, point: LayoutPoint, positionM: number): EanCabinPosition {
  return {
    nodeId: segment.id,
    x: point.x,
    y: point.y,
    segmentId: segment.id,
    positionM: clamp(positionM, 0, segment.length_m),
    fromNodeId: segment.from_node_id,
    toNodeId: segment.to_node_id,
    segmentLengthM: segment.length_m,
    resourceId: segment.resource_id,
  };
}

function pointOnSegment(segment: TrackSegment, layout: ScenarioLayout, rawT: number): LayoutPoint | null {
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

export function groupEventsByCabin(events: EanPhysicalEvent[]) {
  const result = new Map<number, EanPhysicalEvent[]>();
  for (const event of events) {
    const cabinEvents = result.get(event.cabin_id) ?? [];
    cabinEvents.push(event);
    result.set(event.cabin_id, cabinEvents);
  }
  for (const cabinEvents of result.values()) {
    cabinEvents.sort((left, right) => left.time_seconds - right.time_seconds || eventOrder(left) - eventOrder(right));
  }
  return result;
}

function latestEventAtOrBefore(events: EanPhysicalEvent[], timeSeconds: number) {
  let latest: EanPhysicalEvent | null = null;
  for (const event of events) {
    if (event.time_seconds > timeSeconds) break;
    latest = event;
  }
  return latest;
}

function eventsNearTime(events: EanPhysicalEvent[], timeSeconds: number, toleranceSeconds: number) {
  return events.filter((event) => event.time_seconds >= 0 && Math.abs(event.time_seconds - timeSeconds) <= toleranceSeconds);
}

export function eanReplayTimeBounds(replay: EanPhysicalReplay | null) {
  if (!replay || replay.events.length === 0) return { min: 0, max: 0 };
  return {
    min: 0,
    max: replay.model_end_seconds,
  };
}

export function advanceReplayTime(current: number, deltaSeconds: number, min: number, max: number) {
  if (max <= min) return min;
  const next = current + deltaSeconds;
  return clamp(next, min, max);
}

export function isReplayBoundary(timeSeconds: number, direction: PlaybackDirection, min: number, max: number) {
  if (max <= min) return true;
  return direction === 1 ? timeSeconds >= max : timeSeconds <= min;
}

function replayStartTimeForDirection(timeSeconds: number, direction: PlaybackDirection, min: number, max: number) {
  if (direction === 1 && timeSeconds >= max) return min;
  if (direction === -1 && timeSeconds <= min) return max;
  return timeSeconds;
}

function eventOrder(event: EanPhysicalEvent) {
  const order = ["reach_next_switch", "enter_switch", "enter_platform", "enter_wait", "exit_wait", "exit_platform", "exit_switch"];
  return order.indexOf(event.event_kind);
}

function eventKey(event: EanPhysicalEvent) {
  return `${event.cabin_id}:${event.visit_index}:${event.event_kind}:${event.time_seconds}`;
}

function releaseSeconds(serviceStartTime: string, arrivalTime: string) {
  return timeOfDaySeconds(arrivalTime) - timeOfDaySeconds(serviceStartTime);
}

function timeOfDaySeconds(value: string) {
  const [hours = 0, minutes = 0, seconds = 0] = value.split(":").map(Number);
  return hours * 3600 + minutes * 60 + seconds;
}

export function clockLabel(startTime: string, secondsAfterStart: number) {
  const [hours = 0, minutes = 0, seconds = 0] = startTime.split(":").map(Number);
  const totalSeconds = hours * 3600 + minutes * 60 + seconds + secondsAfterStart;
  const totalTenths = Math.round((((totalSeconds % 86400) + 86400) % 86400) * 10) % (86400 * 10);
  const wholeSeconds = Math.floor(totalTenths / 10);
  const tenths = totalTenths % 10;
  const hh = Math.floor(wholeSeconds / 3600);
  const mm = Math.floor((wholeSeconds % 3600) / 60);
  const ss = wholeSeconds % 60;
  const base = `${pad2(hh)}:${pad2(mm)}:${pad2(ss)}`;
  if (tenths === 0) return base;
  return `${base}.${tenths}`;
}

function pad2(value: number) {
  return String(value).padStart(2, "0");
}

export function formatSeconds(seconds: number) {
  return `${seconds.toFixed(1)}s`;
}

function formatOptionalSeconds(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  return formatSeconds(value);
}

function formatLoad(loadCount: number, capacity: number) {
  return `${loadCount} / ${capacity}`;
}

function formatPassengerHours(value: number | null | undefined) {
  if (value === null || value === undefined) return "n/a";
  return `${value.toFixed(1)} pax-h`;
}

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  return `${(value * 100).toFixed(value < 0.01 ? 2 : 1)}%`;
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}
