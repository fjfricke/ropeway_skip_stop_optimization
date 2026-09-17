import { useEffect, useMemo, useState } from "react";
import { Curve, progressColors, type Series } from "./GreedyProgressPanel";
import "./greedy-progress.css";

type Point = { seconds: number; ub: number | null; lb: number | null; gap_percent: number | null };
type Cabin = { cabin_id: number; dispatch_seconds: number; return_seconds: number; waiting_seconds: number; passenger_assignments: number; rounds: string[][] };
type Trial = {
  k: number; status: string; solver_status?: string | null; budget_seconds?: number; elapsed_seconds: number;
  seed_objective_seconds?: number | null; objective_seconds?: number | null; lower_bound_seconds?: number | null;
  gap_percent?: number | null; served?: number | null; unserved?: number | null; used_fleet?: number | null;
  mean_served_journey_seconds?: number | null; native_strict_improvement?: boolean | null;
  points: Point[]; plan?: { cabins: Cabin[] } | null;
};
type AllStopReference = { served: number; unserved: number; used_fleet: number; journey_objective_seconds: number; label: string };
type Detail = { schema: string; campaign_id: string; status: string; updated_unix: number; all_stop_reference?: AllStopReference | null; trials: Trial[] };

const fmt = (value: number | null | undefined, digits = 1) => value == null ? "—" : value.toLocaleString("de-DE", { maximumFractionDigits: digits });

export default function FleetContinuationDashboard({ campaignId }: { campaignId: string }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [selectedK, setSelectedK] = useState<number | null>(null);
  const [follow, setFollow] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let stopped = false;
    async function poll() {
      try {
        const response = await fetch(`/generated/optimization/${encodeURIComponent(campaignId)}/detail.json?t=${Date.now()}`, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const value = await response.json() as Detail;
        if (!stopped) { setDetail(value); setError(null); }
      } catch (cause) {
        if (!stopped) setError(cause instanceof Error ? cause.message : "Live detail unavailable");
      }
      if (!stopped) window.setTimeout(poll, 1000);
    }
    poll(); return () => { stopped = true; };
  }, [campaignId]);
  const visible = detail?.trials.filter(trial => trial.status !== "queued" || trial.points.length || trial.objective_seconds != null) ?? [];
  const latest = visible.at(-1) ?? detail?.trials[0];
  const selected = follow ? latest : detail?.trials.find(trial => trial.k === selectedK) ?? latest;
  const fleetTrials = detail?.trials.filter(trial => trial.objective_seconds != null) ?? [];
  const maxK = Math.max(1, detail?.all_stop_reference?.used_fleet ?? 1, ...fleetTrials.map(trial => trial.k));
  const fleetSeries = useMemo((): { service: Series[]; journey: Series[] } => ({
    service: [
      { name: "Validierter Fahrplan", color: progressColors[0], points: fleetTrials.map(trial => ({ x: trial.k, y: trial.served ?? null })) },
      ...(detail?.all_stop_reference ? [{ name: `All-Stop · K=${detail.all_stop_reference.used_fleet}`, color: "#e56a22", dashed: true, points: [{ x: 0, y: detail.all_stop_reference.served }, { x: maxK, y: detail.all_stop_reference.served }] }] : []),
    ],
    journey: [
      { name: "Journey-Time-Ziel", color: progressColors[2], points: fleetTrials.map(trial => ({ x: trial.k, y: trial.objective_seconds ?? null })) },
      ...(detail?.all_stop_reference ? [{ name: `All-Stop · K=${detail.all_stop_reference.used_fleet}`, color: "#e56a22", dashed: true, points: [{ x: 0, y: detail.all_stop_reference.journey_objective_seconds }, { x: maxK, y: detail.all_stop_reference.journey_objective_seconds }] }] : []),
    ],
  }), [detail, fleetTrials, maxK]);
  const elapsed = Math.max(selected?.elapsed_seconds ?? 0, selected?.points.at(-1)?.seconds ?? 0);
  const bounds: Series[] = selected ? [
    { name: "UB · gültige Lösung", color: progressColors[0], step: true, points: extend(selected.points.map(point => ({ x: point.seconds, y: point.ub })), elapsed) },
    { name: "LB · Solver-Schranke", color: progressColors[2], step: true, points: extend(selected.points.map(point => ({ x: point.seconds, y: point.lb })), elapsed) },
  ] : [];
  const gaps: Series[] = selected ? [{ name: "Relativer Gap", color: progressColors[3], step: true, points: extend(selected.points.map(point => ({ x: point.seconds, y: point.gap_percent })), elapsed) }] : [];
  if (!detail) return <section className="optimization-panel"><div className="optimization-empty">{error ? `Live detail: ${error}` : "Lade Solververläufe…"}</div></section>;
  return <div className="greedy-dashboard fleet-continuation-dashboard">
    {error && <div className="optimization-warning">Live detail: {error}. Der letzte gültige Stand bleibt sichtbar.</div>}
    <section className="optimization-panel">
      <div className="panel-heading"><div><p className="eyebrow">Schrittweise Flottenerweiterung</p><h2>Was bringt eine größere verfügbare Flotte?</h2></div><span>Validierte Lösungen · Bounds gelten jeweils nur für K</span></div>
      <div className="greedy-two-charts"><Curve series={fleetSeries.service} xMax={maxK} xLabel="Flottengrenze K" yLabel="Bediente Personen"/><Curve series={fleetSeries.journey} xMax={maxK} xLabel="Flottengrenze K" yLabel="Journey-Time-Ziel · Personen-s" zero={false}/></div>
      <p className="greedy-note">Jeder Punkt ist der beste unabhängig validierte Fahrplan der betreffenden K-Stufe. Die gestrichelten Linien zeigen denselben validierten All-Stop-Fahrplan mit K=38 als feste Referenz; sie behaupten keine Erreichbarkeit bei kleineren Flottengrenzen. Eine fallende Journey-Time-Kurve kann aus mehr Bedienung, früheren Ankünften oder beidem entstehen.</p>
    </section>
    <section className="optimization-panel">
      <div className="panel-heading"><div><p className="eyebrow">Einzelner vollständiger CP-SAT-Lauf</p><h2>K-Stufe im Detail</h2></div><span>{detail.status === "running" ? "Live · Aktualisierung jede Sekunde" : "Gespeicherter Verlauf"}</span></div>
      <div className="greedy-controls">
        <label>Flottengrenze<select value={selected?.k ?? ""} onChange={event => { setSelectedK(Number(event.target.value)); setFollow(false); }}>{detail.trials.map(trial => <option key={trial.k} value={trial.k}>K≤{trial.k} · {trial.status}</option>)}</select></label>
        <label className="greedy-follow"><input type="checkbox" checked={follow} onChange={event => setFollow(event.target.checked)}/>Neueste aktive Stufe verfolgen</label>
      </div>
      {!selected ? <p className="greedy-empty">Noch keine K-Stufe verfügbar.</p> : <>
        <dl className="greedy-facts">
          <div><dt>Status</dt><dd>{selected.solver_status ?? selected.status}</dd></div>
          <div><dt>UB</dt><dd>{fmt(selected.objective_seconds ?? selected.points.at(-1)?.ub)}</dd></div>
          <div><dt>LB</dt><dd>{fmt(selected.lower_bound_seconds ?? selected.points.at(-1)?.lb)}</dd></div>
          <div><dt>Gap</dt><dd>{fmt(selected.gap_percent ?? selected.points.at(-1)?.gap_percent, 2)} %</dd></div>
          <div><dt>Bedient</dt><dd>{fmt(selected.served, 0)} / {fmt((selected.served ?? 0) + (selected.unserved ?? 0), 0)}</dd></div>
          <div><dt>Eingesetzte Kabinen</dt><dd>{fmt(selected.used_fleet, 0)} von K≤{selected.k}</dd></div>
        </dl>
        <div className="greedy-two-charts"><Curve key={`bounds-${selected.k}`} series={bounds} xMax={Math.max(1, selected.budget_seconds ?? elapsed)} xLabel="Sekunden seit Stufenbeginn" yLabel="Journey-Time-Ziel · Personen-s" zero={false}/><Curve key={`gap-${selected.k}`} series={gaps} xMax={Math.max(1, selected.budget_seconds ?? elapsed)} xLabel="Sekunden seit Stufenbeginn" yLabel="Gap · %"/></div>
        <p className="greedy-note">UB und LB gehören ausschließlich zum vollständigen Modell mit der ausgewählten Flottengrenze. Der Startplan aus K−1 ist nur ein Hint. Gap = (UB − LB) / |UB|.</p>
        <PlanSketch trial={selected}/>
      </>}
    </section>
  </div>;
}

function PlanSketch({ trial }: { trial: Trial }) {
  const cabins = trial.plan?.cabins ?? [];
  if (!cabins.length) return <p className="greedy-empty">Für diese Stufe liegt noch kein exportierter Fahrplan vor.</p>;
  return <details className="greedy-history fleet-plan" open><summary>Aktueller Fahrplan · {cabins.length} eingesetzte Kabinen</summary><div className="fleet-plan-grid">{cabins.map(cabin => <article key={cabin.cabin_id}><header><strong>Cabin {cabin.cabin_id + 1}</strong><span>{fmt(cabin.dispatch_seconds)}s → {fmt(cabin.return_seconds)}s</span></header><p>{cabin.rounds.map((round, index) => <span key={index} title={`Runde ${index + 1}`}>{round.join(" · ") || "all-skip"}</span>)}</p><small>{fmt(cabin.passenger_assignments, 0)} Zuordnungen · {fmt(cabin.waiting_seconds)}s Waiting</small></article>)}</div></details>;
}

function extend(points: Series["points"], elapsed: number) {
  if (!points.length) return points;
  return [...points, { ...points.at(-1)!, x: Math.max(elapsed, points.at(-1)!.x) }];
}
