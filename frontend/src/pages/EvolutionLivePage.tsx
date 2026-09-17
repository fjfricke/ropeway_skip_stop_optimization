import { useEffect, useMemo, useState } from "react";
import GreedyProgressPanel, { type GreedyProgressData, type AllStopReference } from "./GreedyProgressPanel";

type Point = { journey_time_tick?: number; elapsed_seconds: number; served: number; unserved: number; fleet_size: number; pattern_counts: Record<string, number>; total_wait_tick?: number; repair_status?: string | null };
type PatternSubproblem = { elapsed_seconds: number; timing_status: string; native_status?: string; subproblem: string; served?: number | null; pattern_ids?: string[]; preparation_seconds?: number; model_build_seconds?: number; solve_seconds?: number; validation_seconds?: number };
type Run = { fixed_k?: number | null; maximum_cabins?: number; fleet_evaluations?: Record<string, number>; catalog_profile?: string; allowed_pattern_count?: number; pattern_search?: string; progress?: GreedyProgressData; all_stop_reference?: AllStopReference | null; objective?: string; schema: string; label: string; status: string; time_limit_seconds: number; reference_served: number | null; reference_journey_time_tick?: number | null; elapsed_seconds?: number; evaluations: number; feasible_evaluations: number; best: Point | null; best_mixed: Point | null; incumbents: Point[]; mixed_incumbents: Point[]; repair_counts: Record<string, number>; repair_seconds: number; last_improvement_seconds?: number; updated_unix: number; representation?: string; dispatch_subproblem?: string; timing_status_counts?: Record<string, number>; last_pattern_subproblem?: PatternSubproblem; last_insertion?: { kind?: string; insertion_k?: number; served?: number; local_unserved_bound?: number } };
type ConflictPoint = { elapsed_seconds: number; mean: number | null; minimum: number | null; maximum: number | null; complete: number; population: number; construction_failed: number; unmeasured: number };
type ConflictData = { runs: Record<string, ConflictPoint[]>; infeasible?: Record<string, ConflictPoint[]>; missing?: Record<string, ConflictPoint[]>; errors?: Record<string, string> };
type Manifest = { schema: string; label: string; status: string; completed_runs?: number; total_runs?: number; runs: { id: string; label: string; snapshot: string }[] };

export default function EvolutionLivePage() {
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [runs, setRuns] = useState<Record<string, Run>>({});
  const [conflicts, setConflicts] = useState<ConflictData>({ runs: {} });
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let stopped = false;
    async function poll() {
      try {
        const m = await fetch(`/generated/evolution-live/manifest.json?t=${Date.now()}`, { cache: "no-store" }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() as Promise<Manifest>; });
        const values = await Promise.all(m.runs.map(async item => {
          const response = await fetch(`${item.snapshot}?t=${Date.now()}`, { cache: "no-store" });
          const json = response.headers.get("content-type")?.includes("application/json");
          return [item.id, response.ok && json ? await response.json() as Run : null] as const;
        }));
        if (!stopped) {
          const available: Record<string, Run> = {};
          for (const [id, value] of values) if (value) available[id] = value;
          setManifest(m); setRuns(available); setError(null);
          const c = await fetch(`/generated/evolution-live/conflicts.json?t=${Date.now()}`, { cache: "no-store" });
          if (!stopped && c.ok && c.headers.get("content-type")?.includes("application/json")) setConflicts(await c.json());
        }
      } catch (cause) { if (!stopped) setError(cause instanceof Error ? cause.message : "Live data unavailable"); }
      if (!stopped) window.setTimeout(poll, 1000);
    }
    poll(); return () => { stopped = true; };
  }, []);
  const running = Object.values(runs).some(run => run.status === "running");
  const demand = Object.values(runs).flatMap(run => run.incumbents).map(point => point.served + point.unserved).find(Number.isFinite);
  return <main className="optimization-shell evolution-live">
    <header className="optimization-hero"><div><p className="eyebrow">Reservoir line evolution</p><h1>{manifest?.label ?? "Live search"}</h1></div><div className="campaign-status"><span className={`run-state run-state--${running ? "running" : manifest?.status ?? "queued"}`}>{running ? "running" : manifest?.status ?? "connecting"}</span><strong>{manifest?.completed_runs ?? Object.keys(runs).length}/{manifest?.total_runs ?? manifest?.runs.length ?? 0} complete</strong></div></header>
    {error && <div className="optimization-warning">Live data: {error}</div>}
    {Object.values(runs).some(r => r.representation === "greedy") ? <GreedyProgressPanel runs={runs}/> : <>
    <section className="optimization-panel"><div className="panel-heading"><h2>Validated service over search time</h2><span>{Object.values(runs).some(r => r.representation === "greedy") ? "Greedy · validated insertions" : demand == null ? "Validated passengers" : `Total demand · ${demand.toLocaleString()} passengers`}</span></div><EvolutionChart runs={runs} /></section>
    {Object.values(runs).some(r => r.objective === "journey_time" || r.objective === "service_then_journey") && <section className="optimization-panel"><div className="panel-heading"><h2>Validated journey tie-break over search time</h2><span>Person-seconds · compared only after service · lower is better</span></div><EvolutionChart runs={runs} timeCost /></section>}
    {Object.values(runs).some(r => r.representation === "greedy") ? <section className="optimization-panel"><h2>Insertion progress</h2><p>Existing trajectories stay fixed. Each new cabin chooses its dispatch anywhere in the warmup. Bounds apply only to the current insertion.</p>{Object.entries(runs).map(([id, r]) => <p key={id}>{r.label}: K={r.best?.fleet_size ?? 0} · {r.feasible_evaluations} validated native solutions · latest insertion K={r.last_insertion?.insertion_k ?? "—"} · local unserved bound {r.last_insertion?.local_unserved_bound ?? "—"}</p>)}</section> : Object.values(runs).some(r => r.representation !== "patterns_only") ? <ConflictChart runs={runs} data={conflicts} /> : null}
    <section className="evolution-run-grid">{manifest?.runs.map(meta => <RunPanel key={meta.id} meta={meta} run={runs[meta.id]} />)}</section>
    </>}
  </main>;
}

function RunPanel({ meta, run }: { meta: Manifest["runs"][number]; run?: Run }) {
  if (!run) return <section className="optimization-panel evolution-run"><div className="panel-heading"><h2>{meta.label}</h2><span>queued</span></div><div className="optimization-empty">Waiting for this run.</div></section>;
  const best = run.best; const age = best ? Math.max(0, (run.elapsed_seconds ?? 0) - best.elapsed_seconds) : null;
  const repairs = Object.entries(run.repair_counts).reduce((sum, [, n]) => sum + n, 0);
  const timing = Object.entries(run.timing_status_counts ?? {}).reduce((sum, [, n]) => sum + n, 0);
  return <section className="optimization-panel evolution-run">
    <div className="panel-heading"><h2>{run.label}</h2><span className={`run-state run-state--${run.status}`}>{run.status}</span></div>
    {run.allowed_pattern_count != null && <p className="evolution-conflict-note">Catalog: {run.catalog_profile} · {run.allowed_pattern_count} allowed patterns · {run.pattern_search === "line_groups" ? "Joint line changes; initially 2–5 lines, no hard line limit" : "Independent cabin pattern changes"}</p>}
    {run.maximum_cabins != null && <p className="evolution-conflict-note">{run.fixed_k == null ? `Variable fleet: 1–${run.maximum_cabins} cabins` : `Fixed fleet: ${run.fixed_k} cabins`} · {Object.keys(run.fleet_evaluations ?? {}).length} fleet sizes evaluated · latest candidate K={run.last_pattern_subproblem?.pattern_ids?.length ?? "—"}</p>}
    <div className="metric-strip"><Metric label={run.objective === "journey_time" ? "Served in best plan" : "Best served"} value={best?.served.toLocaleString() ?? "—"} /><Metric label="Fleet" value={best ? `K=${best.fleet_size}` : "—"} />{run.objective === "journey_time" || run.objective === "service_then_journey" ? <Metric label={run.objective === "service_then_journey" ? "Journey tie-break · person-s" : "Time cost · person-s"} value={best?.journey_time_tick == null ? "—" : (best.journey_time_tick / 1e6).toLocaleString(undefined, {maximumFractionDigits: 1})} /> : <Metric label="Best mixed" value={run.best_mixed?.served.toLocaleString() ?? "—"} />}<Metric label="Since improvement" value={age == null ? "—" : `${age.toFixed(0)} s`} /><Metric label="Progress" value={`${(run.elapsed_seconds ?? 0).toFixed(0)} / ${run.time_limit_seconds.toFixed(0)} s`} /></div>
    <div className="evolution-meter"><i style={{ transform: `scaleX(${Math.min(1, (run.elapsed_seconds ?? 0) / run.time_limit_seconds)})` }} /></div>
    <div className="evolution-detail"><div><span>{run.representation === "greedy" ? "Accepted insertions" : "Evaluations"}</span><strong>{run.evaluations.toLocaleString()}</strong><small>{run.feasible_evaluations.toLocaleString()} valid</small></div>{run.representation === "patterns_only" ? <div><span>Timing subproblems</span><strong>{timing.toLocaleString()}</strong><small>{Object.entries(run.timing_status_counts ?? {}).map(([s,n]) => `${n} ${s.replace("PATTERN_", "").toLowerCase()}`).join(" · ") || "waiting"}</small></div> : <div><span>Waiting repairs</span><strong>{repairs.toLocaleString()}</strong><small>{Object.entries(run.repair_counts).map(([s,n]) => `${n} ${s.toLowerCase()}`).join(" · ") || "disabled"}</small></div>}<div><span>Current pattern mix</span><strong>{best ? Object.keys(best.pattern_counts).length : 0} patterns</strong><small>{best ? formatPatterns(best.pattern_counts) : run.last_pattern_subproblem?.pattern_ids ? formatPatterns(Object.fromEntries(run.last_pattern_subproblem.pattern_ids.map(p => [p, run.last_pattern_subproblem!.pattern_ids!.filter(x => x === p).length]))) : "No incumbent yet"}</small></div></div>
  </section>;
}

function EvolutionChart({ runs, timeCost = false }: { runs: Record<string, Run>; timeCost?: boolean }) {
  const entries = Object.entries(runs); const demand = entries.flatMap(([,r]) => r.incumbents).map(p => p.served + p.unserved).find(Number.isFinite); const maxX = Math.max(1, ...entries.map(([,r]) => r.time_limit_seconds)); const maxY = Math.max(timeCost ? 1 : demand ?? 1, ...entries.flatMap(([,r]) => r.incumbents.map(p => timeCost ? (p.journey_time_tick ?? 0) / 1e6 : p.served)));
  const sx = (x:number) => 48 + x/maxX*512; const sy = (y:number) => 178-y/maxY*146;
  const reference = timeCost ? Object.values(runs).find(r => r.reference_journey_time_tick != null)?.reference_journey_time_tick != null ? Object.values(runs).find(r => r.reference_journey_time_tick != null)!.reference_journey_time_tick! / 1e6 : null : demand ?? Object.values(runs).find(r => r.reference_served != null)?.reference_served ?? null;
  const paths = useMemo(() => entries.map(([id,run]) => ({ id, points: stepPoints(timeCost ? run.incumbents.filter(p => p.journey_time_tick != null).map(p => ({...p, served: p.journey_time_tick! / 1e6})) : run.incumbents, sx, sy) })), [runs, timeCost]);
  return <figure className="bound-chart evolution-chart"><svg viewBox="0 0 600 220" role="img" aria-label={timeCost ? "Validated time cost over elapsed seconds" : "Validated passengers over elapsed seconds"}><line x1="48" y1="178" x2="570" y2="178" className="chart-axis" /><line x1="48" y1="24" x2="48" y2="178" className="chart-axis" />{reference != null && <><line x1="48" y1={sy(reference)} x2="570" y2={sy(reference)} className="evolution-reference" /><text x="565" y={sy(reference)-5} textAnchor="end">{timeCost ? "All-Stop" : "Demand"} {reference.toLocaleString()}</text></>}{paths.map((p,i) => <polyline key={p.id} points={p.points} className={`evolution-line evolution-line--${i}`} />)}<text x="570" y="205" textAnchor="end">elapsed seconds</text><text x="53" y="18">{timeCost ? "person-seconds" : "served"}</text></svg><figcaption>{entries.map(([id,r],i) => <span className={`evolution-key evolution-key--${i}`} key={id}>{r.label}</span>)}</figcaption></figure>;
}
function stepPoints(points: Point[], sx:(x:number)=>number, sy:(y:number)=>number) { let prior: Point | undefined; const out:string[]=[]; for (const p of points) { if (prior) out.push(`${sx(p.elapsed_seconds)},${sy(prior.served)}`); out.push(`${sx(p.elapsed_seconds)},${sy(p.served)}`); prior=p; } return out.join(" "); }
function formatPatterns(patterns: Record<string,number>) { return Object.entries(patterns).sort((a,b)=>b[1]-a[1]).map(([p,n]) => `${n}× ${p.replaceAll("stop_", "").replaceAll("_", "–")}`).join(" · "); }
function Metric({label,value}:{label:string;value:string}) { return <div><span>{label}</span><strong>{value}</strong></div>; }


function ConflictChart({ runs, data }: { runs: Record<string, Run>; data: ConflictData }) {
  const [metric, setMetric] = useState<"mean" | "minimum" | "maximum">("mean");
  const [scope, setScope] = useState<"infeasible" | "runs" | "missing">("infeasible");
  const series = data[scope] ?? {};
  const entries = Object.entries(runs);
  const maxX = Math.max(1, ...entries.map(([, r]) => r.time_limit_seconds));
  const maxY = Math.max(1, ...entries.flatMap(([id]) => (series[id] ?? []).map(p => p[metric] ?? 0)));
  const sx = (x: number) => 55 + x / maxX * 505;
  const sy = (y: number) => 178 - y / maxY * 146;
  const format = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 1 });
  return <section className="optimization-panel">
    <div className="panel-heading"><h2>Conflicts over search time</h2><label>View <select value={scope} onChange={e => setScope(e.target.value as typeof scope)}><option value="infeasible">Unrepaired candidates · before Waiting</option><option value="missing">Failed construction · missing cabins</option><option value="runs">Population · after Waiting</option></select></label>{scope !== "infeasible" && <label>Statistic <select value={metric} onChange={e => setMetric(e.target.value as typeof metric)}><option value="mean">Mean</option><option value="minimum">Minimum</option><option value="maximum">Maximum</option></select></label>}</div>
    <p className="evolution-conflict-note">{scope === "infeasible" ? "Each point is a complete unrepaired candidate. No-Wait physical conflicts are recorded directly or reconstructed from patterns and dispatches. Includes disabled, unsuccessful and unresolved repair attempts; this is not a Waiting infeasibility proof." : scope === "missing" ? "Number of unplaced cabins among failed constructions in each population snapshot. This is construction progress, not a count of physical conflicts." : "Physical conflicts in fully constructed population members after any repair. Incomplete constructions are excluded."}</p>
    {Object.entries(data.errors ?? {}).map(([id, message]) => <p key={id} className="optimization-warning">{id}: conflict replay unavailable — {message}</p>)}
    <figure className="bound-chart evolution-chart"><svg viewBox="0 0 600 220" role="img" aria-label={`${metric} physical conflicts in the population over search time`}>
      {[0, 0.5, 1].map(f => <g key={f}><line x1="55" y1={sy(f*maxY)} x2="560" y2={sy(f*maxY)} className="chart-axis" /><text x="48" y={sy(f*maxY)+4} textAnchor="end">{format(f*maxY)}</text></g>)}
      <line x1="55" y1="24" x2="55" y2="178" className="chart-axis" />
      {[0, 0.25, 0.5, 0.75, 1].map(f => <text key={f} x={sx(f*maxX)} y="193" textAnchor="middle">{Math.round(f*maxX/60)}</text>)}
      {entries.map(([id], i) => {
        let penDown = false;
        const path = (series[id] ?? []).map(p => {
          const value = p[metric];
          if (value == null) { penDown = false; return ""; }
          const command = `${penDown ? "L" : "M"}${sx(p.elapsed_seconds)},${sy(value)}`;
          penDown = true; return command;
        }).join(" ");
        const last = (series[id] ?? []).at(-1);
        return <g key={id}><path d={path} className={`evolution-line evolution-line--${i}`} />{last && last[metric] != null && <circle cx={sx(last.elapsed_seconds)} cy={sy(last[metric]!)} r="2.5" className={`evolution-line evolution-line--${i}`}><title>{runs[id].label}: {format(last[metric]!)} conflicts</title></circle>}</g>;
      })}
      <text x="560" y="212" textAnchor="end">elapsed minutes</text><text x="55" y="17">{scope === "missing" ? "unplaced cabins" : "conflicts"} · {scope === "infeasible" ? "per candidate" : metric}</text>
    </svg><figcaption>{entries.map(([id, run], i) => {
      const last = (series[id] ?? []).at(-1);
      return <span className={`evolution-key evolution-key--${i}`} key={id}>{run.label}: {last && last[metric] != null ? format(last[metric]!) : "—"}{last ? scope === "infeasible" ? ` · ${(series[id] ?? []).length} unrepaired candidates` : scope === "missing" ? ` · ${last.complete} failed constructions` : ` · ${last.complete}/${last.population} measured · ${last.construction_failed} construction failures` : " · no measurements yet"}</span>;
    })}</figcaption></figure>
  </section>;
}
