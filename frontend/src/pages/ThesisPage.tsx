import { useEffect, useMemo, useState } from "react";
import type { ThesisGroup, ThesisIndex, ThesisRunSummary } from "../thesisTypes";
import { bestRun, groupRuns, matchingAllStop, plannedThesisIndex, referenceLabel } from "../thesisPresentation";
import ThesisPreflight from "../components/ThesisPreflight";
import ThesisRunDetail from "../components/ThesisRunDetail";

const familyNames = { f0: "Diffuse", f2: "Complementary", f3: "Express", f4: "Local" };

export default function ThesisPage() {
  const [index, setIndex] = useState<ThesisIndex>(plannedThesisIndex);
  const [notice, setNotice] = useState("Planned matrix — no result package loaded");
  const [objective, setObjective] = useState<"all" | ThesisGroup["objective"]>("all");
  const [topology, setTopology] = useState<"all" | ThesisGroup["topology"]>("all");
  const [resolution, setResolution] = useState("15");
  const [fleet, setFleet] = useState("all");
  const [demand, setDemand] = useState("all");
  const [selected, setSelected] = useState<string | null>(() => new URLSearchParams(window.location.search).get("run"));

  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;
    async function poll() {
      let nextDelay = 5000;
      try {
        const response = await fetch(`/generated/thesis/index.json?t=${Date.now()}`, { cache: "no-store" });
        const isJson = response.headers.get("content-type")?.includes("application/json");
        if (!response.ok || !isJson) throw new Error(response.ok ? "response is not JSON" : `HTTP ${response.status}`);
        const loaded = await response.json() as ThesisIndex;
        const value = loaded.contractId === plannedThesisIndex.contractId
          ? { ...loaded, runs: loaded.runs.filter((run) => run.studyMembership === "current_thesis") }
          : plannedThesisIndex;
        if (value.schema !== "thesis_frontend_index_v1" || !Array.isArray(value.groups) || !Array.isArray(value.runs)) {
          throw new Error("unsupported result manifest");
        }
        if (!stopped) {
          setIndex(value);
          setNotice(value === plannedThesisIndex
            ? "No result package for the current contract — earlier packages are in the archive"
            : value.generatedAt ? `Data package · ${new Date(value.generatedAt).toLocaleString()}` : "Result package loaded");
          nextDelay = valueDelay(value.campaignStatus);
        }
      } catch (cause) {
        if (!stopped) setNotice(`Data refresh failed; showing last available view · ${cause instanceof Error ? cause.message : "data unavailable"}`);
      }
      if (!stopped) timer = window.setTimeout(poll, nextDelay);
    }
    poll();
    return () => { stopped = true; if (timer !== undefined) window.clearTimeout(timer); };
  }, []);

  const visible = useMemo(() => index.groups.filter((group) =>
    (objective === "all" || group.objective === objective)
    && (topology === "all" || group.topology === topology)
  ), [index.groups, objective, topology]);
  const completed = index.runs.filter((run) => run.status === "complete").length;
  const filteredIndex = { ...index, runs: index.runs.filter(run =>
    (resolution === "all" || run.releaseResolutionSeconds === Number(resolution))
    && (run.method === "all_stop_phase" || ((fleet === "all" || run.k === Number(fleet)) && (demand === "all" || run.demand === Number(demand))))
  ) };
  const selectedRun = index.runs.find(run => run.id === selected);
  useEffect(() => {
    const select = () => setSelected(new URLSearchParams(window.location.search).get("run"));
    window.addEventListener("popstate", select);
    return () => window.removeEventListener("popstate", select);
  }, []);

  return <main className="thesis-shell">
    <header className="thesis-masthead">
      <div><p className="eyebrow">Thesis experiment atlas</p><h1>Where does Skip-Stop pay?</h1></div>
      <div className="thesis-masthead__status"><span className={`run-state run-state--${index.campaignStatus === "running" ? "running" : "complete"}`}>{index.campaignStatus}</span><strong>{completed}/{index.runs.length || "—"} completed runs</strong><small>{notice}</small>{index.launchReadiness && <small>Series gates: {index.launchReadiness.groups.filter(g => !g.blockers.length).length}/{index.launchReadiness.groups.length} passed · main study not automatically started</small>}</div>
    </header>

    <ThesisPreflight />

    <section className="thesis-contract" aria-label="Frozen experiment contract">
      <div><span>Track</span><strong>G500</strong><small>500 m free rope per section</small></div>
      <div><span>Window</span><strong>2 cycles</strong><small>+ 900 s completion · + 300 s continued movement</small></div>
      <div><span>Journey starts</span><strong>Fixed balanced</strong><small>T5R/G500 · geometric headways</small></div>
      <div><span>OIP starts</span><strong>Optimized</strong><small>No-Wait first · independently validated</small></div>
    </section>

    <section className="thesis-controls" aria-label="Filter experiment matrix">
      <div><p className="eyebrow">Experiment matrix</p><h2>Current frozen comparisons</h2></div>
      <label>Objective<select value={objective} onChange={(event) => setObjective(event.target.value as typeof objective)}><option value="all">All</option><option value="unserved">Capacity</option><option value="journey_time">Journey time</option></select></label>
      <label>Topology<select value={topology} onChange={(event) => setTopology(event.target.value as typeof topology)}><option value="all">All</option><option value="t5r">T5R</option><option value="t6r">T6R</option></select></label>
      <label>Release resolution<select value={resolution} onChange={e => setResolution(e.target.value)}><option value="all">All · separate results</option>{[30, 15, 5].map(n => <option key={n} value={n}>{n} s</option>)}</select></label>
      <label>Fleet K<select value={fleet} onChange={e => setFleet(e.target.value)}><option value="all">All fleets</option>{[...new Set(index.runs.map(run => run.k).filter((k): k is number => k != null))].sort((a, b) => a - b).map(k => <option key={k}>{k}</option>)}</select></label>
      <label>Demand N<select value={demand} onChange={e => setDemand(e.target.value)}><option value="all">All loads · no pooled ranking</option>{[...new Set(index.runs.filter(run => run.method !== "all_stop_phase").map(run => run.demand).filter((n): n is number => n != null))].sort((a, b) => a - b).map(n => <option key={n}>{n}</option>)}</select></label>
    </section>

    <section className="thesis-matrix">
      {visible.map((group) => {
        const refs = groupRuns(filteredIndex, group).filter(run => run.reference && (resolution !== "all" || run.reference.releaseResolutionSeconds === 15));
        refs.sort((a, b) => Number(b.reference?.capacityProven) - Number(a.reference?.capacityProven) || (b.reference?.provenFeasibleDemand ?? 0) - (a.reference?.provenFeasibleDemand ?? 0));
        return <GroupRow key={group.id} group={{ ...group, reference: refs[0]?.reference ?? undefined }} index={filteredIndex} onSelect={setSelected} blockers={index.launchReadiness?.groups.find(g => g.id === group.id)?.blockers} />;
      })}
    </section>
    {selectedRun && <ThesisRunDetail run={selectedRun} comparison={matchingAllStop(selectedRun, index.runs)} />}

    <section className="thesis-archive" aria-label="Research archive">
      <div><p className="eyebrow">Research archive</p><h2>Trace every optimization run</h2></div>
      <a href="/optimization"><strong>Current optimization campaigns</strong><span>Only runs declaring this thesis contract</span></a>
      <a href="/archive"><strong>Historical experiments</strong><span>Earlier contracts, evolution diagnostics and exploratory runs</span></a>
    </section>

    <footer className="thesis-sources">
      <p className="eyebrow">Model provenance</p>
      <p>6 m/s rope · 0.3 m/s platform · 10 passengers · 1 m/s² acceleration. Station paths remain separate from the free-rope length.</p>
      {index.sources?.map((source) => <a key={source.url} href={source.url} target="_blank" rel="noreferrer"><strong>{source.label}</strong><span>{source.use}</span></a>)}
    </footer>
  </main>;
}

function GroupRow({ group, index, onSelect, blockers }: { group: ThesisGroup; index: ThesisIndex; onSelect: (id: string) => void; blockers?: string[] }) {
  const runs = groupRuns(index, group);
  const best = bestRun(runs, group.objective);
  const active = runs.find((run) => run.status === "running");
  const multipleDemands = new Set(runs.filter(run => run.method !== "all_stop_phase").map(run => run.demand)).size > 1;
  return <article className="thesis-group">
    <div className="thesis-group__identity"><span>{group.topology.toUpperCase()} · {group.demandFamily.toUpperCase()}</span><h3>{familyNames[group.demandFamily]}</h3><small>{group.objective === "unserved" ? "Capacity witness" : "Full-service journey time"}</small></div>
    <div className="thesis-group__method"><span>Method</span><strong>{group.method === "evolution" ? "Evolutionary line plan" : "Labelled arc-flow"}</strong><small>Fixed K · {runs.length} run{runs.length === 1 ? "" : "s"}</small></div>
    <div className="thesis-group__reference"><span>All-Stop</span><strong>{referenceLabel(group)}</strong><small>{group.reference?.proofScope ?? "Regular No-Wait reference pending"}</small></div>
    <div className="thesis-group__result"><span>{active ? "Live" : "Best validated"}</span><strong>{active ? `K=${active.k ?? "?"} · ${(active.elapsedSeconds ?? 0).toFixed(0)} s` : best ? resultLabel(best, group) : multipleDemands ? "Multiple demand levels · inspect runs" : "Awaiting calibration"}</strong><small>{best?.boundScope ?? "No global claim without a matching bound"}</small></div>
    {blockers && <div className="thesis-group__gates"><small>{blockers.length ? "Series pending: " + blockers.map(b => ({exact_all_stop_reference_pending: "exact All-Stop reference", validated_all_stop_witness_pending: "All-Stop witness", validated_optimization_pilot_pending: "validated optimization pilot", release_resolution_evidence_pending: "release resolution check"}[b] ?? b)).join(" · ") : "Series gates passed for the tested calibration scope"}</small></div>}
    {runs.length > 0 && <details className="thesis-group__runs">
      <summary>Inspect {runs.length} recorded run{runs.length === 1 ? "" : "s"}</summary>
      <div className="thesis-run-list">
        {runs.map((run) => <div className="thesis-run-row" key={run.id}>
          <strong>{run.method === "all_stop_phase" ? "All-Stop reference" : run.method === "evolution" ? "Evolution" : `Labelled arc-flow · ${run.operatingMode === "all_stop" ? "All-Stop" : "Skip-Stop"}`}</strong>
          <span>{run.k != null ? `K=${run.k}` : "K—"} · {run.method === "all_stop_phase" ? "N ceiling=" : "N="}{run.demand ?? "—"} · seed {run.seed ?? "—"}{run.primalSeedKind ? ` · start: ${run.primalSeedKind}` : ""}</span>
          <span>{run.method === "all_stop_phase" ? referenceRunLabel(run) : resultLabel(run, group)}</span>
          <span>{run.status}{run.elapsedSeconds != null ? ` · ${run.elapsedSeconds.toFixed(1)} s` : ""}{run.stopReason ? ` · ${run.stopReason}` : ""}</span>
          {run.snapshot && <a href={run.snapshot} target="_blank" rel="noreferrer">Raw result</a>}
          {run.detail && <button onClick={() => { onSelect(run.id); window.setTimeout(() => document.querySelector(".thesis-detail")?.scrollIntoView({ behavior: "smooth" }), 50); }}>Progress & replay</button>}
          {run.replay && <a href={run.replay} target="_blank" rel="noreferrer">Certificate</a>}
        </div>)}
      </div>
    </details>}
  </article>;
}

function resultLabel(run: NonNullable<ReturnType<typeof bestRun>>, group: ThesisGroup) {
  if (run.validated === false) return "No validated solution";
  if (group.objective === "unserved") return `${run.served?.toLocaleString()} served · K=${run.k ?? "?"}`;
  return `${run.journeyTime?.toLocaleString()} passenger-s · K=${run.k ?? "?"}`;
}

function valueDelay(status: ThesisIndex["campaignStatus"]) {
  return status === "running" || status === "calibrating" ? 1500 : 5000;
}

function referenceRunLabel(run: ThesisIndex["runs"][number]) {
  const reference = run.reference;
  if (!reference) return "Reference result";
  const suffix = reference.releaseResolutionSeconds != null ? ` · ${reference.releaseResolutionSeconds} s` : "";
  if (reference.capacityProven && reference.capacity != null) return `κAS = ${reference.capacity.toLocaleString()}${suffix}`;
  if (reference.provenFeasibleDemand != null && reference.provenInfeasibleDemand != null) {
    return `${reference.provenFeasibleDemand.toLocaleString()} ≤ κAS < ${reference.provenInfeasibleDemand.toLocaleString()}${suffix}`;
  }
  return `Open reference${suffix}`;
}
