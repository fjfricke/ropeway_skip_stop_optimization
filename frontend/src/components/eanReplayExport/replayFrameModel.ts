import type { ScenarioLayout } from "../../scenarioLayout";
import type { EanPassengerServicePlan, Scenario } from "../../types";
import {
  buildEanPassengerState,
  eanCabinMarkersAtTime,
  eanReplayCollisionMarkers,
  EVENT_TOLERANCE_SECONDS,
  groupEventsByCabin,
} from "../EanReplayView";
import type { ReplayCabinMarker, ReplayCollisionMarker, ReplayStationQueueMarker } from "../networkTypes";

export type ReplayVideoFrame = {
  cabins: ReplayCabinMarker[];
  collisions: ReplayCollisionMarker[];
  queues: ReplayStationQueueMarker[];
};

type ReplayVideoPassengerEvent = {
  timeSeconds: number;
  order: number;
  kind: "release" | "board" | "alight";
  groupId: string;
  cabinId?: number;
  destination: string;
  count: number;
};

type ReplayVideoDemandGroup = {
  origin: string;
  destination: string;
  count: number;
};

export function replayFrameAtTime({
  scenario,
  layout,
  eventsByCabin,
  passengerPlan,
  timeSeconds,
}: {
  scenario: Scenario;
  layout: ScenarioLayout;
  eventsByCabin: ReturnType<typeof groupEventsByCabin>;
  passengerPlan: EanPassengerServicePlan | null;
  timeSeconds: number;
}) {
  const passengerState = buildEanPassengerState(scenario, passengerPlan, timeSeconds, EVENT_TOLERANCE_SECONDS);
  const cabins = eanCabinMarkersAtTime(scenario, layout, eventsByCabin, timeSeconds, passengerState.cabinLoadsById);
  return {
    cabins,
    collisions: eanReplayCollisionMarkers(scenario, cabins),
    queues: passengerState.queueMarkers,
  };
}

export function createReplayVideoFrameBuilder({
  scenario,
  layout,
  eventsByCabin,
  passengerPlan,
}: {
  scenario: Scenario;
  layout: ScenarioLayout;
  eventsByCabin: ReturnType<typeof groupEventsByCabin>;
  passengerPlan: EanPassengerServicePlan | null;
}) {
  const passengerTimeline = createPassengerTimeline(scenario, passengerPlan);
  return {
    frameAt(timeSeconds: number): ReplayVideoFrame {
      const passengerState = passengerTimeline.advanceTo(timeSeconds);
      const cabins = eanCabinMarkersAtTime(scenario, layout, eventsByCabin, timeSeconds, passengerState.cabinLoadsById);
      return {
        cabins,
        collisions: eanReplayCollisionMarkers(scenario, cabins),
        queues: passengerState.queueMarkers,
      };
    },
  };
}

function createPassengerTimeline(scenario: Scenario, passengerPlan: EanPassengerServicePlan | null) {
  if (!passengerPlan) {
    return {
      advanceTo() {
        return { cabinLoadsById: new Map<number, { loadCount: number; destinationLoads: { destination: string; count: number }[] }>(), queueMarkers: [] };
      },
    };
  }

  const demandByGroupId = new Map<string, ReplayVideoDemandGroup>();
  for (let index = 0; index < scenario.demands.length; index += 1) {
    const demand = scenario.demands[index];
    demandByGroupId.set(`demand::${index}`, {
      origin: demand.origin,
      destination: demand.destination,
      count: demand.count,
    });
  }

  const events: ReplayVideoPassengerEvent[] = [];
  for (let index = 0; index < scenario.demands.length; index += 1) {
    const demand = scenario.demands[index];
    events.push({
      timeSeconds: releaseSeconds(scenario.service_start_time, demand.arrival_time),
      order: 0,
      kind: "release",
      groupId: `demand::${index}`,
      destination: demand.destination,
      count: demand.count,
    });
  }

  for (const ride of passengerPlan?.served_rides ?? []) {
    const demand = demandByGroupId.get(ride.demand_group_id);
    if (!demand) continue;
    events.push({
      timeSeconds: ride.boarding_time_seconds,
      order: 1,
      kind: "board",
      groupId: ride.demand_group_id,
      cabinId: ride.cabin_id,
      destination: demand.destination,
      count: ride.count,
    });
    events.push({
      timeSeconds: ride.alighting_time_seconds,
      order: 2,
      kind: "alight",
      groupId: ride.demand_group_id,
      cabinId: ride.cabin_id,
      destination: demand.destination,
      count: ride.count,
    });
  }

  events.sort((left, right) => left.timeSeconds - right.timeSeconds || left.order - right.order);

  const waitingByGroupId = new Map<string, number>();
  const loadsByCabinId = new Map<number, Map<string, number>>();
  let eventIndex = 0;

  function applyEvent(event: ReplayVideoPassengerEvent) {
    if (event.kind === "release") {
      waitingByGroupId.set(event.groupId, (waitingByGroupId.get(event.groupId) ?? 0) + event.count);
      return;
    }
    if (event.kind === "board") {
      waitingByGroupId.set(event.groupId, Math.max(0, (waitingByGroupId.get(event.groupId) ?? 0) - event.count));
      if (event.cabinId === undefined) return;
      const load = loadsByCabinId.get(event.cabinId) ?? new Map<string, number>();
      load.set(event.destination, (load.get(event.destination) ?? 0) + event.count);
      loadsByCabinId.set(event.cabinId, load);
      return;
    }
    if (event.cabinId === undefined) return;
    const load = loadsByCabinId.get(event.cabinId);
    if (!load) return;
    const nextCount = Math.max(0, (load.get(event.destination) ?? 0) - event.count);
    if (nextCount > 0) {
      load.set(event.destination, nextCount);
    } else {
      load.delete(event.destination);
    }
    if (load.size === 0) loadsByCabinId.delete(event.cabinId);
  }

  return {
    advanceTo(timeSeconds: number) {
      while (eventIndex < events.length && events[eventIndex].timeSeconds <= timeSeconds) {
        applyEvent(events[eventIndex]);
        eventIndex += 1;
      }
      return snapshotPassengerState(demandByGroupId, waitingByGroupId, loadsByCabinId);
    },
  };
}

function snapshotPassengerState(
  demandByGroupId: Map<string, ReplayVideoDemandGroup>,
  waitingByGroupId: Map<string, number>,
  loadsByCabinId: Map<number, Map<string, number>>,
) {
  const cabinLoadsById = new Map<number, { loadCount: number; destinationLoads: { destination: string; count: number }[] }>();
  for (const [cabinId, destinationMap] of loadsByCabinId.entries()) {
    const destinationLoads = [...destinationMap.entries()]
      .filter(([, count]) => count > 0)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([destination, count]) => ({ destination, count }));
    if (destinationLoads.length === 0) continue;
    cabinLoadsById.set(cabinId, {
      loadCount: destinationLoads.reduce((sum, load) => sum + load.count, 0),
      destinationLoads,
    });
  }

  const queuesByStation = new Map<string, ReplayStationQueueMarker>();
  for (const [groupId, waiting] of waitingByGroupId.entries()) {
    if (waiting <= 0) continue;
    const demand = demandByGroupId.get(groupId);
    if (!demand) continue;
    const queue = queuesByStation.get(demand.origin) ?? {
      stationId: demand.origin,
      totalCount: 0,
      destinationQueues: [],
    };
    queue.totalCount += waiting;
    queue.destinationQueues.push({ destination: demand.destination, count: waiting });
    queuesByStation.set(demand.origin, queue);
  }

  const queueMarkers = [...queuesByStation.values()]
    .map((queue) => ({
      ...queue,
      destinationQueues: queue.destinationQueues.sort((left, right) => left.destination.localeCompare(right.destination)),
    }))
    .sort((left, right) => left.stationId.localeCompare(right.stationId));

  return { cabinLoadsById, queueMarkers };
}

function releaseSeconds(serviceStartTime: string, arrivalTime: string) {
  return timeOfDaySeconds(arrivalTime) - timeOfDaySeconds(serviceStartTime);
}

function timeOfDaySeconds(value: string) {
  const [hours = 0, minutes = 0, seconds = 0] = value.split(":").map(Number);
  return hours * 3600 + minutes * 60 + seconds;
}
