import { useEffect, useState } from "react";

type Gate = {
  id: string;
  status: string;
  wallSeconds?: number;
  capacity?: number | null;
  provenFeasibleDemand?: number;
  provenInfeasibleDemand?: number | null;
  served?: number | null;
  unserved?: number | null;
  upperBound?: number | null;
  lowerBound?: number | null;
  validation?: string;
};
type Snapshot = {
  schema: "thesis_preflight_view_v1";
  status: string;
  startedAt: string;
  generatedAt: string;
  plannedJobs: number;
  jobs: Gate[];
};

function outcome(gate: Gate) {
  if (gate.capacity != null) return `κAS = ${gate.capacity.toLocaleString()}`;
  if (gate.provenFeasibleDemand != null) {
    return gate.provenInfeasibleDemand != null
      ? `${gate.provenFeasibleDemand.toLocaleString()} ≤ κAS < ${gate.provenInfeasibleDemand.toLocaleString()}`
      : `κAS ≥ ${gate.provenFeasibleDemand.toLocaleString()}`;
  }
  if (gate.served != null) return `${gate.served.toLocaleString()} served · ${gate.unserved ?? "?"} unserved`;
  if (gate.validation === "feasible" && gate.upperBound != null) return `${gate.upperBound.toLocaleString()} passenger-s`;
  return gate.status === "running" ? "Working · no completed result yet" : "No validated result";
}

export default function ThesisPreflight() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [stale, setStale] = useState(false);
  useEffect(() => {
    let disposed = false;
    let timer: number | undefined;
    async function poll() {
      try {
        const response = await fetch(`/generated/thesis/preflight.json?t=${Date.now()}`, { cache: "no-store" });
        if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) throw new Error("unavailable");
        const value = await response.json() as Snapshot;
        if (value.schema !== "thesis_preflight_view_v1" || !Array.isArray(value.jobs)) throw new Error("schema");
        if (!disposed) { setSnapshot(value); setStale(false); }
      } catch {
        if (!disposed) setStale(true);
      }
      if (!disposed) timer = window.setTimeout(poll, 3000);
    }
    void poll();
    return () => { disposed = true; if (timer != null) window.clearTimeout(timer); };
  }, []);
  if (!snapshot) return null;
  const finished = snapshot.jobs.filter(job => job.status !== "running").length;
  const active = snapshot.jobs.find(job => job.status === "running");
  return <section className="thesis-archive thesis-preflight" aria-label="Calibration gate checks">
    <div><p className="eyebrow">Calibration · separate from the main experiments</p>
      <h2>Resolution & profile checks</h2>
      <p>{finished}/{snapshot.plannedJobs} attempts finished · {snapshot.status}{stale ? " · refresh unavailable" : ""}</p>
      <p>15 s profile tests · 5 s sensitivity · exact K · no primal starts</p>
      {active && <p>Current: <strong>{active.id.replaceAll("_", " ")}</strong></p>}
      <small>Snapshot: {new Date(snapshot.generatedAt).toLocaleTimeString()} · A finished attempt may leave its capacity unresolved.</small>
    </div>
    <details className="thesis-group__runs">
      <summary>Inspect calibration attempts</summary>
      <div className="thesis-run-list">{snapshot.jobs.map(gate => <div className="thesis-run-row" key={gate.id}>
        <strong>{gate.id.replaceAll("_", " ")}</strong>
        <span>{gate.status}</span><span>{outcome(gate)}</span>
        <span>{gate.wallSeconds != null ? `${gate.wallSeconds.toFixed(1)} s` : "—"}</span>
      </div>)}</div>
    </details>
  </section>;
}
