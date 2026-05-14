import { useMemo } from "react";
import type { Scenario } from "../types";
import { DemandSummaryPanel, type DemandSummaryRow } from "./DemandSummaryPanel";

interface DemandPanelProps {
  scenario: Scenario;
}

export function DemandPanel({ scenario }: DemandPanelProps) {
  const rows = useMemo(() => aggregateDemand(scenario), [scenario]);
  const total = rows.reduce((sum, row) => sum + row.count, 0);

  return <DemandSummaryPanel total={total} rows={rows} stations={scenario.stations} />;
}

function aggregateDemand(scenario: Scenario): DemandSummaryRow[] {
  const byOd = new Map<string, { origin: string; destination: string; count: number; times: string[] }>();
  for (const demand of scenario.demands) {
    const key = `${demand.origin}-${demand.destination}`;
    const current = byOd.get(key) ?? {
      origin: demand.origin,
      destination: demand.destination,
      count: 0,
      times: [],
    };
    current.count += demand.count;
    current.times.push(demand.arrival_time);
    byOd.set(key, current);
  }
  return [...byOd.values()].map((row) => ({
    id: `${row.origin}-${row.destination}`,
    origin: row.origin,
    destination: row.destination,
    count: row.count,
    detail: `${row.times[0]}-${row.times[row.times.length - 1]}`,
  }));
}
