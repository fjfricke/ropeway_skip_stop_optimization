import { CircleAlert, FastForward, Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { cumulativeDemandQueues, demandArrivalsAtStep, totalDemandCount, type DemandArrivalRow, type DemandQueueRow } from "../replayDemand";
import { layoutForScenario } from "../scenarioLayout";
import type {
  AlightingEvent,
  BoardingEvent,
  CabinLoadState,
  DiscreteNode,
  DiscreteScenario,
  MovementPlan,
  PassengerQueueState,
  PassengerReplayResult,
  Scenario,
} from "../types";
import { DemandSummaryPanel, type DemandSummaryRow } from "./DemandSummaryPanel";
import { NetworkSvg, type ReplayCabinMarker, type ReplayStationQueueMarker } from "./NetworkSvg";
import { useNetworkPanelContentHeight } from "./useNetworkPanelContentHeight";
import type { ArcColorMode, DiscreteViewerToggles, ViewerToggles } from "./viewerTypes";

interface ReplayViewProps {
  scenario: Scenario;
  discreteScenario: DiscreteScenario | null;
  movementPlan: MovementPlan | null;
  passengerReplay: PassengerReplayResult | null;
  movementPlanWarning: string | null;
  passengerReplayWarning: string | null;
  toggles: ViewerToggles;
  arcColorMode: ArcColorMode;
}

const REPLAY_DISCRETE_TOGGLES: DiscreteViewerToggles = {
  enabled: false,
  showMoveArcs: false,
  showWaitArcs: false,
  showOwnSegmentHeadway: false,
  showAdjacentSegmentHeadway: false,
  showMultiSegmentHeadway: false,
};

const SPEED_OPTIONS = [0.5, 1, 2, 5];

export function ReplayView({
  scenario,
  discreteScenario,
  movementPlan,
  passengerReplay,
  movementPlanWarning,
  passengerReplayWarning,
  toggles,
  arcColorMode,
}: ReplayViewProps) {
  const networkPanelRef = useRef<HTMLDivElement | null>(null);
  const sidePanelMaxHeight = useNetworkPanelContentHeight(networkPanelRef);
  const layout = useMemo(() => layoutForScenario(scenario), [scenario]);
  const [timeStep, setTimeStep] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const [selectedCabinId, setSelectedCabinId] = useState<number | null>(movementPlan?.trajectories[0]?.cabin_id ?? null);

  const maxStep = movementPlan?.horizon_steps ?? 0;
  const nodeById = useMemo(
    () => new Map((discreteScenario?.nodes ?? []).map((node) => [node.id, node])),
    [discreteScenario],
  );
  const passengerStep = passengerReplay?.steps[timeStep] ?? null;
  const currentPositions = useMemo(
    () => (movementPlan ? positionsAtStep(movementPlan, timeStep, passengerStep?.cabin_loads ?? [], discreteScenario?.cabin_capacity ?? 0) : []),
    [discreteScenario, movementPlan, passengerStep, timeStep],
  );
  const demandQueues = useMemo(
    () => {
      const passengerStep = passengerReplay?.steps[timeStep];
      if (passengerStep) return passengerStep.queue_states.map(passengerQueueToDemandQueue);
      return cumulativeDemandQueues(discreteScenario?.demands ?? [], timeStep);
    },
    [discreteScenario, passengerReplay, timeStep],
  );
  const demandArrivals = useMemo(
    () => demandArrivalsAtStep(discreteScenario?.demands ?? [], timeStep),
    [discreteScenario, timeStep],
  );
  const waitingDemandCount = useMemo(() => totalDemandCount(demandQueues), [demandQueues]);
  const demandQueueRows = useMemo(
    () => demandQueues.map((queue) => demandQueueRow(queue, scenario.service_start_time, discreteScenario?.delta_seconds ?? 1)),
    [demandQueues, discreteScenario, scenario.service_start_time],
  );
  const boardingEvents = passengerStep?.boarding_events ?? [];
  const alightingEvents = passengerStep?.alighting_events ?? [];
  const replayStationQueues = useMemo(() => stationQueueMarkers(demandQueues), [demandQueues]);
  const selectedPosition = currentPositions.find((position) => position.cabinId === selectedCabinId) ?? currentPositions[0] ?? null;
  const selectedNode = selectedPosition ? nodeById.get(selectedPosition.nodeId) ?? null : null;
  const selectedCabinLoad = selectedPosition && passengerStep
    ? passengerStep.cabin_loads.find((load) => load.cabin_id === selectedPosition.cabinId) ?? null
    : null;

  useEffect(() => {
    setTimeStep((current) => Math.min(current, maxStep));
  }, [maxStep]);

  useEffect(() => {
    if (!isPlaying || !movementPlan) return;
    const intervalMs = Math.max(40, 500 / playbackSpeed);
    const interval = window.setInterval(() => {
      setTimeStep((current) => {
        if (current >= movementPlan.horizon_steps) return 0;
        return current + 1;
      });
    }, intervalMs);
    return () => window.clearInterval(interval);
  }, [isPlaying, movementPlan, playbackSpeed]);

  if (!discreteScenario || !movementPlan) {
    return (
      <section className="replay-empty">
        <CircleAlert size={18} />
        <strong>{movementPlanWarning ?? "Replay unavailable"}</strong>
      </section>
    );
  }

  return (
    <section className="replay-view">
      <div className="network-panel replay-network" ref={networkPanelRef}>
        <div className="network-panel__header">
          <div>
            <h2>Cabin Replay</h2>
            <p>Greedy all-stop circulation with passenger boarding replay</p>
          </div>
          <div className="status-pill">
            <FastForward size={16} />
            {movementPlan.trajectories.length} cabins · {movementPlan.paths[0]?.id ?? "movement plan"}
          </div>
        </div>
        <NetworkSvg
          scenario={scenario}
          discreteScenario={discreteScenario}
          layout={layout}
          selected={null}
          hovered={null}
          toggles={toggles}
          arcColorMode={arcColorMode}
          discreteMode="selected"
          discreteToggles={REPLAY_DISCRETE_TOGGLES}
          replayCabins={currentPositions}
          replayStationQueues={replayStationQueues}
          selectedCabinId={selectedCabinId}
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
            <button onClick={() => setTimeStep((current) => Math.max(0, current - 1))} aria-label="Previous step">
              <SkipBack size={16} />
            </button>
            <button className="replay-play" onClick={() => setIsPlaying((current) => !current)}>
              {isPlaying ? <Pause size={16} /> : <Play size={16} />}
              {isPlaying ? "Pause" : "Play"}
            </button>
            <button onClick={() => setTimeStep((current) => Math.min(maxStep, current + 1))} aria-label="Next step">
              <SkipForward size={16} />
            </button>
          </div>
          <input
            aria-label="Replay time step"
            className="replay-slider"
            type="range"
            min="0"
            max={maxStep}
            value={timeStep}
            onChange={(event) => setTimeStep(Number(event.target.value))}
          />
          <div className="replay-time">
            <strong>{timeStep}</strong>
            <span>/ {maxStep} steps</span>
            <span>{clockLabel(scenario.service_start_time, timeStep, discreteScenario.delta_seconds)}</span>
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

        <DemandSummaryPanel
          total={waitingDemandCount}
          rows={demandQueueRows}
          emptyMessage="No waiting passengers"
          className="replay-demand-panel"
        >
          <DemandArrivalList
            arrivals={demandArrivals}
            startTime={scenario.service_start_time}
            deltaSeconds={discreteScenario.delta_seconds}
          />
          <PassengerEventList
            boardingEvents={boardingEvents}
            alightingEvents={alightingEvents}
            deltaSeconds={discreteScenario.delta_seconds}
          />
        </DemandSummaryPanel>

        <section className="panel">
          <header className="panel__header">
            <FastForward size={17} />
            <h2>Cabin Inspector</h2>
          </header>
          {selectedPosition ? (
            <div className="kv-list">
              <h3>C{selectedPosition.cabinId}</h3>
              <div className="kv-row">
                <span>time step</span>
                <strong>{timeStep}</strong>
              </div>
              <div className="kv-row">
                <span>node</span>
                <strong>{selectedPosition.nodeId}</strong>
              </div>
              <div className="kv-row">
                <span>incoming</span>
                <strong>{selectedPosition.incomingArcId ?? "none"}</strong>
              </div>
              <CabinLoadRows load={selectedCabinLoad} capacity={discreteScenario.cabin_capacity} />
              {selectedNode ? <ReplayNodeRows node={selectedNode} /> : null}
            </div>
          ) : (
            <div className="empty-panel">No cabin</div>
          )}
        </section>

        <section className="panel">
          <header className="panel__header">
            <CircleAlert size={17} />
            <h2>Replay Status</h2>
          </header>
          <div className="metric-grid">
            <div className="metric">
              <span>served</span>
              <strong>{passengerReplay?.summary.served_passengers ?? "n/a"}</strong>
            </div>
            <div className="metric">
              <span>waiting</span>
              <strong>{passengerReplay?.summary.unserved_passengers ?? waitingDemandCount}</strong>
            </div>
            <div className="metric">
              <span>onboard</span>
              <strong>{passengerReplay?.summary.onboard_passengers ?? "n/a"}</strong>
            </div>
            <div className="metric">
              <span>policy</span>
              <strong>{passengerReplay ? "greedy FIFO" : "queue only"}</strong>
            </div>
          </div>
          {passengerReplayWarning ? <p className="panel-note">{passengerReplayWarning}</p> : null}
        </section>
      </aside>
    </section>
  );
}

function DemandArrivalList({
  arrivals,
  startTime,
  deltaSeconds,
}: {
  arrivals: DemandArrivalRow[];
  startTime: string;
  deltaSeconds: number;
}) {
  if (arrivals.length === 0) return null;

  return (
    <div className="arrival-list" aria-label="Demand arrivals at current step">
      {arrivals.map((arrival) => (
        <div className="arrival-row" key={arrival.demandIndex}>
          <span>
            +{arrival.count} {arrival.origin} {"->"} {arrival.destination}
          </span>
          <small>{demandClockLabel(startTime, arrival.timeStep, deltaSeconds)}</small>
        </div>
      ))}
    </div>
  );
}

function PassengerEventList({
  boardingEvents,
  alightingEvents,
  deltaSeconds,
}: {
  boardingEvents: BoardingEvent[];
  alightingEvents: AlightingEvent[];
  deltaSeconds: number;
}) {
  if (boardingEvents.length === 0 && alightingEvents.length === 0) return null;

  return (
    <div className="passenger-event-list" aria-label="Passenger events at current step">
      {boardingEvents.map((event, index) => (
        <div className="passenger-event passenger-event--boarding" key={`boarding-${event.batch_id}-${event.cabin_id}-${index}`}>
          <span>
            C{event.cabin_id} boards {event.count} to {event.destination}
          </span>
          <small>{formatDuration(event.waiting_steps, deltaSeconds)} wait</small>
        </div>
      ))}
      {alightingEvents.map((event, index) => (
        <div className="passenger-event passenger-event--alighting" key={`alighting-${event.batch_id}-${event.cabin_id}-${index}`}>
          <span>
            C{event.cabin_id} unloads {event.count} at {event.station_id}
          </span>
          <small>{formatDuration(event.onboard_steps, deltaSeconds)} onboard</small>
        </div>
      ))}
    </div>
  );
}

function CabinLoadRows({ load, capacity }: { load: CabinLoadState | null; capacity: number }) {
  const loadCount = load ? load.onboard_groups.reduce((sum, group) => sum + group.count, 0) : 0;
  return (
    <>
      <div className="kv-row">
        <span>load</span>
        <strong>
          {loadCount} / {capacity}
        </strong>
      </div>
      {load?.onboard_groups.length ? (
        <div className="onboard-list">
          {load.onboard_groups.map((group) => (
            <div className="onboard-row" key={`${group.batch_id}-${group.boarded_step}-${group.destination}`}>
              <span>
                {group.origin} {"->"} {group.destination}
              </span>
              <strong>{group.count}</strong>
            </div>
          ))}
        </div>
      ) : null}
    </>
  );
}

function ReplayNodeRows({ node }: { node: DiscreteNode }) {
  return (
    <>
      <div className="kv-row">
        <span>physical</span>
        <strong>{node.source_physical_node_id ?? "none"}</strong>
      </div>
      <div className="kv-row">
        <span>segment</span>
        <strong>{node.source_segment_id ?? "none"}</strong>
      </div>
      <div className="kv-row">
        <span>position</span>
        <strong>{node.position_m === null ? "n/a" : `${roundOne(node.position_m)} m`}</strong>
      </div>
      <div className="kv-row">
        <span>station</span>
        <strong>{node.station_id ?? "none"}</strong>
      </div>
    </>
  );
}

function positionsAtStep(
  plan: MovementPlan,
  timeStep: number,
  cabinLoads: CabinLoadState[],
  capacity: number,
): ReplayCabinMarker[] {
  const loadByCabinId = new Map(cabinLoads.map((load) => [load.cabin_id, load]));
  return plan.trajectories.flatMap((trajectory) => {
    const position = trajectory.positions[timeStep];
    if (!position) return [];
    const load = loadByCabinId.get(trajectory.cabin_id);
    return [{
      cabinId: trajectory.cabin_id,
      nodeId: position.node_id,
      incomingArcId: position.incoming_arc_id,
      loadCount: load ? load.onboard_groups.reduce((sum, group) => sum + group.count, 0) : 0,
      capacity,
      destinationLoads: load ? destinationLoads(load) : [],
    }];
  });
}

function destinationLoads(load: CabinLoadState): { destination: string; count: number }[] {
  const byDestination = new Map<string, number>();
  for (const group of load.onboard_groups) {
    byDestination.set(group.destination, (byDestination.get(group.destination) ?? 0) + group.count);
  }
  return [...byDestination.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([destination, count]) => ({ destination, count }));
}

function clockLabel(startTime: string, timeStep: number, deltaSeconds: number) {
  const [hours = 0, minutes = 0, seconds = 0] = startTime.split(":").map(Number);
  const totalSeconds = hours * 3600 + minutes * 60 + seconds + timeStep * deltaSeconds;
  const normalized = ((totalSeconds % 86400) + 86400) % 86400;
  const wholeSeconds = Math.floor(normalized);
  const fraction = normalized - wholeSeconds;
  const hh = Math.floor(wholeSeconds / 3600);
  const mm = Math.floor((wholeSeconds % 3600) / 60);
  const ss = wholeSeconds % 60;
  const base = `${pad2(hh)}:${pad2(mm)}:${pad2(ss)}`;
  if (fraction < 0.001) return base;
  return `${base}.${Math.round(fraction * 10)}`;
}

function pad2(value: number) {
  return String(value).padStart(2, "0");
}

function roundOne(value: number) {
  return Math.round(value * 10) / 10;
}

function demandQueueRow(queue: DemandQueueRow, startTime: string, deltaSeconds: number): DemandSummaryRow {
  return {
    id: `${queue.origin}-${queue.destination}`,
    origin: queue.origin,
    destination: queue.destination,
    count: queue.count,
    detail: queueStepWindow(queue, startTime, deltaSeconds),
  };
}

function passengerQueueToDemandQueue(queue: PassengerQueueState): DemandQueueRow {
  return {
    origin: queue.station_id,
    destination: queue.destination,
    count: queue.waiting_count,
    firstStep: queue.time_step,
    lastStep: queue.time_step,
  };
}

function stationQueueMarkers(queues: DemandQueueRow[]): ReplayStationQueueMarker[] {
  const byStation = new Map<string, ReplayStationQueueMarker>();
  for (const queue of queues) {
    const current = byStation.get(queue.origin) ?? {
      stationId: queue.origin,
      totalCount: 0,
      destinationQueues: [],
    };
    current.totalCount += queue.count;
    current.destinationQueues.push({ destination: queue.destination, count: queue.count });
    byStation.set(queue.origin, current);
  }
  return [...byStation.values()].map((queue) => ({
    ...queue,
    destinationQueues: queue.destinationQueues.sort((left, right) => left.destination.localeCompare(right.destination)),
  }));
}

function queueStepWindow(queue: DemandQueueRow, startTime: string, deltaSeconds: number) {
  const first = demandClockLabel(startTime, queue.firstStep, deltaSeconds);
  const last = demandClockLabel(startTime, queue.lastStep, deltaSeconds);
  if (first === last) return first;
  return `${first}-${last}`;
}

function formatDuration(steps: number, deltaSeconds: number) {
  const seconds = steps * deltaSeconds;
  if (seconds < 60) return `${roundOne(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  if (remainder === 0) return `${minutes}m`;
  return `${minutes}m ${remainder}s`;
}

function demandClockLabel(startTime: string, timeStep: number, deltaSeconds: number) {
  const label = clockLabel(startTime, timeStep, deltaSeconds);
  if (label.endsWith(":00")) return label.slice(0, 5);
  return label;
}
