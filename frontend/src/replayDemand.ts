import type { DiscreteDemand } from "./types";

export interface DemandQueueRow {
  origin: string;
  destination: string;
  count: number;
  firstStep: number;
  lastStep: number;
}

export interface DemandArrivalRow {
  demandIndex: number;
  timeStep: number;
  origin: string;
  destination: string;
  count: number;
}

export function cumulativeDemandQueues(demands: DiscreteDemand[], timeStep: number): DemandQueueRow[] {
  const byOd = new Map<string, DemandQueueRow>();

  for (let index = 0; index < demands.length; index += 1) {
    const demand = demands[index];
    if (demand.time_step > timeStep) continue;

    const key = `${demand.origin}->${demand.destination}`;
    const current = byOd.get(key);
    if (current) {
      current.count += demand.count;
      current.firstStep = Math.min(current.firstStep, demand.time_step);
      current.lastStep = Math.max(current.lastStep, demand.time_step);
      continue;
    }

    byOd.set(key, {
      origin: demand.origin,
      destination: demand.destination,
      count: demand.count,
      firstStep: demand.time_step,
      lastStep: demand.time_step,
    });
  }

  return [...byOd.values()].sort((left, right) => (
    left.origin.localeCompare(right.origin) ||
    left.destination.localeCompare(right.destination)
  ));
}

export function demandArrivalsAtStep(demands: DiscreteDemand[], timeStep: number): DemandArrivalRow[] {
  return demands.flatMap((demand, index) => {
    if (demand.time_step !== timeStep) return [];
    return [{
      demandIndex: index,
      timeStep: demand.time_step,
      origin: demand.origin,
      destination: demand.destination,
      count: demand.count,
    }];
  });
}

export function totalDemandCount(rows: DemandQueueRow[]): number {
  return rows.reduce((sum, row) => sum + row.count, 0);
}
