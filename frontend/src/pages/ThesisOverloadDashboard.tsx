import { useEffect, useMemo, useState } from "react";
import { Curve, progressColors, type Series } from "./GreedyProgressPanel";
import "./greedy-progress.css";

type Point = {
  seconds: number;
  ub: number;
  lb: number | null;
  gap_percent: number | null;
  served: number | null;
  unserved: number | null;
  journey_time_seconds: number | null;
  used_fleet: number | null;
  served_lower_bound?: number | null;
  served_upper_bound?: number | null;
  journey_time_lower_bound?: number | null;
  type_counts?: Record<string, number> | null;
  termination_reason?: string | null;
  reference_served_cutoff?: number | null;
};
type Detail = {
  eyebrow?: string;
  title?: string;
  subtitle?: string;
  reference_label?: string;
  status: string;
  elapsed_seconds: number;
  demand_total: number;
  fleet_cap: number;
  all_stop_capacity: number;
  maximum_wait_seconds?: number;
  maximum_used_wait_seconds?: number;
  total_used_wait_seconds?: number;
  passenger_horizon_seconds?: number;
  operation_seconds?: number;
  pattern_composition?: Record<string, number> | null;
  type_catalog?: string | null;
  type_counts?: Record<string, number> | null;
  termination_reason?: string | null;
  reference_served_cutoff?: number | null;
  solve_mode?: string;
  passenger_evaluation?: { status?: string } | null;
  passenger_encoding?: string;
  native_incumbent_seen?: boolean;
  inherited_start?: boolean;
  inherited_start_value?: Point | null;
  reference?: Point | null;
  latest: Point;
  points: Point[];
  termination?: string | null;
  model_stats?: Record<string, number>;
  headway_contract?: string;
  reduction_stats?: { shared_intervals?: number; resource_intervals?: number; fixed_type_specialization?: boolean; mechanical_resource_families?: number };
  backend?: string;
  formulation?: string;
  objective?: string;
  operation?: string;
  active_fleet?: number | null;
  initial_placement?: string | null;
  initial_states?: Array<{ cabin_id: number; kind: string; switch_id: string; progress: number; previous_event_time_seconds: number; next_event_time_seconds: number }>;
  stop_count?: number | null;
  skip_count?: number | null;
  build_seconds?: number | null;
  search_seconds?: number | null;
  peak_rss_gb?: number | null;
};

const fmt = (value: number | null | undefined, digits = 1) =>
  value == null ? "—" : value.toLocaleString("de-DE", { maximumFractionDigits: digits });

function extend(points: Series["points"], elapsed: number) {
  if (!points.length) return points;
  return [...points, { ...points.at(-1)!, x: Math.max(elapsed, points.at(-1)!.x) }];
}

export default function ThesisOverloadDashboard({ campaignId, finished = false }: { campaignId: string; finished?: boolean }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;
    async function poll() {
      try {
        const response = await fetch(`/generated/optimization/${encodeURIComponent(campaignId)}/detail.json?t=${Date.now()}`, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const value = await response.json() as Detail;
        if (!stopped) { setDetail(value); setError(null); }
        if (!stopped && !finished && !["complete", "failed", "resource_limit", "interrupted"].includes(value.status)) timer = window.setTimeout(poll, 2000);
      } catch (cause) {
        if (!stopped) { setError(cause instanceof Error ? cause.message : "Live-Daten nicht verfügbar"); timer = window.setTimeout(poll, 2000); }
      }
    }
    poll();
    return () => { stopped = true; if (timer !== undefined) window.clearTimeout(timer); };
  }, [campaignId, finished]);

  const charts = useMemo(() => {
    if (!detail) return null;
    const elapsed = Math.max(1, detail.elapsed_seconds, detail.points.at(-1)?.seconds ?? 0);
    const ref = detail.reference;
    const line = (value: number) => [{ x: 0, y: value }, { x: elapsed, y: value }];
    return {
      elapsed,
      service: [
        { name: "Validierter Incumbent", color: progressColors[0], step: true, points: extend(detail.points.filter(p => p.served != null).map(p => ({ x: p.seconds, y: p.served! })), elapsed) },
        ...(ref?.served != null ? [{ name: `All-Stop · ${fmt(ref.served, 0)}`, color: "#e56a22", dashed: true, points: line(ref.served) }] : []),
        { name: `Nachfrage · ${fmt(detail.demand_total, 0)}`, color: "#777e89", dashed: true, points: line(detail.demand_total) },
      ] satisfies Series[],
      journey: [
        { name: "Journey Time desselben Incumbents", color: progressColors[2], step: true, points: extend(detail.points.filter(p => p.journey_time_seconds != null).map(p => ({ x: p.seconds, y: p.journey_time_seconds! })), elapsed) },
        ...(ref?.journey_time_seconds != null ? [{ name: "All-Stop", color: "#e56a22", dashed: true, points: line(ref.journey_time_seconds) }] : []),
      ] satisfies Series[],
      bounds: [
        { name: "UB · gültige Lösung", color: progressColors[0], step: true, points: extend(detail.points.map(p => ({ x: p.seconds, y: p.ub })), elapsed) },
        { name: "LB · Solver-Schranke", color: progressColors[2], step: true, points: extend(detail.points.map(p => ({ x: p.seconds, y: p.lb })), elapsed) },
        ...(ref && (detail.objective === "minimize_unserved" ? ref.unserved : ref.ub) != null ? [{ name: "All-Stop-Startwert", color: "#e56a22", dashed: true, points: line((detail.objective === "minimize_unserved" ? ref.unserved : ref.ub)!) }] : []),
      ] satisfies Series[],
      gap: [{ name: detail.objective === "minimize_unserved" ? "Served-Gap" : "Lexikografischer Gap", color: progressColors[3], step: true, points: extend(detail.points.map(p => ({ x: p.seconds, y: p.gap_percent })), elapsed) }] satisfies Series[],
    };
  }, [detail]);

  if (!detail || !charts) return <section className="optimization-panel"><div className="optimization-empty">{error ? `Live-Daten: ${error}` : "Lade Überlast-Pilot…"}</div></section>;
  const latest = detail.latest;
  const hasNativeIncumbent = detail.native_incumbent_seen ?? true;
  const referenceLabel = detail.reference_label ?? "All-Stop";
  const hasReference = detail.reference != null;
  const movementOnly = detail.solve_mode === "movement_feasibility";
  return <div className="greedy-dashboard overload-dashboard">
    {error && <div className="optimization-warning">Live-Daten: {error}. Der letzte gültige Stand bleibt sichtbar.</div>}
    <section className="optimization-panel">
      <div className="panel-heading"><div><p className="eyebrow">{detail.eyebrow ?? "Vollständiges Reservoir-CP-SAT"}</p><h2>{detail.title ?? "110 % der All-Stop-Kapazität"}</h2></div><span>{detail.subtitle ?? `T5R · G500 · F2 · P0 · K≤${detail.fleet_cap} · ${detail.passenger_encoding ?? "groups"}`}</span></div>
      <dl className="greedy-facts overload-facts">
        <div><dt>Status</dt><dd>{detail.termination_reason === "cannot_beat_reference" ? "Referenz nicht schlagbar" : detail.status.replaceAll("_", " ")}</dd></div>
        {!movementOnly && <div><dt>Incumbent</dt><dd>{hasNativeIncumbent ? fmt(latest.ub, 0) : "—"}</dd></div>}
        {!movementOnly && <div><dt>Lower Bound</dt><dd>{fmt(latest.lb, 0)}</dd></div>}
        {!movementOnly && <div><dt>Gap</dt><dd>{fmt(latest.gap_percent, 2)}{latest.gap_percent == null ? "" : " %"}</dd></div>}
        <div><dt>Bedient</dt><dd>{hasNativeIncumbent ? `${fmt(latest.served, 0)} / ${fmt(detail.demand_total, 0)}` : "—"}</dd></div>
        {(latest.served_lower_bound != null || latest.served_upper_bound != null) && <div><dt>Bedienungsschranken</dt><dd>{fmt(latest.served_lower_bound, 0)}–{fmt(latest.served_upper_bound, 0)}</dd></div>}
        <div><dt>Journey Time</dt><dd>{hasNativeIncumbent ? `${fmt(latest.journey_time_seconds)} Personen-s${detail.objective === "minimize_unserved" ? " · gemessen" : ""}` : "—"}</dd></div>
        {latest.journey_time_lower_bound != null && <div><dt>Journey-LB</dt><dd>{fmt(latest.journey_time_lower_bound)} Personen-s</dd></div>}
        <div><dt>Waiting</dt><dd>{detail.maximum_wait_seconds == null ? "—" : `≤ ${fmt(detail.maximum_wait_seconds, 0)} s`}</dd></div>
        {detail.maximum_used_wait_seconds != null && <div><dt>Waiting genutzt</dt><dd>max. {fmt(detail.maximum_used_wait_seconds, 3)} s · gesamt {fmt(detail.total_used_wait_seconds, 3)} s</dd></div>}
        {detail.passenger_evaluation?.status && <div><dt>Passagierprüfung</dt><dd>{detail.passenger_evaluation.status.replaceAll("_", " ")}</dd></div>}
        {detail.passenger_horizon_seconds != null && <div><dt>Zeitfenster</dt><dd>Service {fmt(detail.passenger_horizon_seconds, 0)} s · Betrieb {fmt(detail.operation_seconds, 0)} s</dd></div>}
        {detail.pattern_composition && <div><dt>Muster</dt><dd>{Object.entries(detail.pattern_composition).map(([pattern, count]) => `${count}× ${pattern}`).join(" · ")}</dd></div>}
        {detail.type_counts && <div><dt>Kabinentypen</dt><dd>{Object.entries(detail.type_counts).filter(([, count]) => count > 0).map(([type, count]) => `${count}× ${type.replaceAll("_", " ")}`).join(" · ")}</dd></div>}
        {detail.backend && <div><dt>Backend</dt><dd>{detail.backend.replaceAll("_", " ")}</dd></div>}
        {detail.formulation && <div><dt>Formulierung</dt><dd>{detail.formulation.replaceAll("_", " ")}</dd></div>}
        {detail.inherited_start && <div><dt>Start-Hint</dt><dd>{fmt(detail.inherited_start_value?.ub, 0)} · separat</dd></div>}
        {detail.active_fleet != null && <div><dt>Aktive Flotte</dt><dd>{detail.active_fleet} / {detail.fleet_cap}</dd></div>}
        {detail.initial_placement && <div><dt>Anfangsaufstellung</dt><dd>{detail.initial_placement}</dd></div>}
        {(detail.stop_count != null || detail.skip_count != null) && <div><dt>STOP / SKIP</dt><dd>{fmt(detail.stop_count, 0)} / {fmt(detail.skip_count, 0)}</dd></div>}
        {detail.build_seconds != null && <div><dt>Aufbau</dt><dd>{fmt(detail.build_seconds)} s</dd></div>}
        {detail.search_seconds != null && <div><dt>Suche</dt><dd>{fmt(detail.search_seconds)} s</dd></div>}
        {detail.peak_rss_gb != null && <div><dt>Speicher</dt><dd>{fmt(detail.peak_rss_gb, 2)} GiB</dd></div>}
        {detail.model_stats?.variables != null && <div><dt>Variablen</dt><dd>{fmt(detail.model_stats.variables, 0)}</dd></div>}
        {detail.model_stats?.constraints != null && <div><dt>Constraints</dt><dd>{fmt(detail.model_stats.constraints, 0)}</dd></div>}
        {detail.model_stats?.intervals != null && <div><dt>Ressourcenintervalle</dt><dd>{fmt(detail.model_stats.intervals, 0)}</dd></div>}
        {detail.reduction_stats?.shared_intervals != null && <div><dt>Geteilte Headway-Intervalle</dt><dd>{fmt(detail.reduction_stats.shared_intervals, 0)} redundante Kopien entfallen</dd></div>}
        {detail.reduction_stats?.fixed_type_specialization && <div><dt>Typaufbau</dt><dd>Ein festes Template je Kabine</dd></div>}
        {detail.headway_contract && <div><dt>Headways</dt><dd>{detail.headway_contract === "geometric_shared_entry_exit_v1" ? "Geometrisch · ohne Weichenzuschläge" : detail.headway_contract}</dd></div>}
        {detail.model_stats?.presolved_variables != null && <div><dt>Nach Presolve</dt><dd>{fmt(detail.model_stats.presolved_variables, 0)} Variablen · {fmt(detail.model_stats.presolved_constraints, 0)} Constraints</dd></div>}
      </dl>
      <div className="greedy-two-charts"><Curve series={charts.service} xMax={charts.elapsed} xLabel="Sekunden" yLabel="Bediente Personen"/><Curve series={charts.journey} xMax={charts.elapsed} xLabel="Sekunden" yLabel="Journey Time · Personen-s" zero={false}/></div>
      <p className="greedy-note">Beide Kurven zeigen denselben unabhängig validierten Incumbent. {hasReference ? `Orange gestrichelt: ${referenceLabel}. ` : ""}Grau gestrichelt: vollständige Nachfrage.</p>
      {!!detail.initial_states?.length && <details className="greedy-note"><summary>Anfangsaufstellung je Kabine</summary><div className="table-scroll"><table><thead><tr><th>Kabine</th><th>Zustand</th><th>Switch</th><th>Fortschritt</th><th>Randintervall</th></tr></thead><tbody>{detail.initial_states.map(state => <tr key={state.cabin_id}><td>{state.cabin_id}</td><td>{state.kind.replaceAll("_", " ")}</td><td>{state.switch_id}</td><td>{fmt(100 * state.progress)} %</td><td>{fmt(state.previous_event_time_seconds)}–{fmt(state.next_event_time_seconds)} s</td></tr>)}</tbody></table></div></details>}
    </section>
    {!movementOnly && <section className="optimization-panel">
      <div className="panel-heading"><div><p className="eyebrow">Solverfortschritt</p><h2>Lower Bound, Upper Bound und Gap</h2></div><span>{detail.objective === "minimize_unserved" ? "Exaktes Ziel: minimale Nichtbedienung" : "Exaktes lexikografisches Ziel: Unserved, dann Journey Time"}</span></div>
      <div className="greedy-two-charts"><Curve series={charts.bounds} xMax={charts.elapsed} xLabel="Sekunden" yLabel={detail.objective === "minimize_unserved" ? "Nichtbediente Personen" : "Lexikografischer Zielwert"} zero={false}/><Curve series={charts.gap} xMax={charts.elapsed} xLabel="Sekunden" yLabel="Gap · %"/></div>
      <p className="greedy-note">{detail.objective === "minimize_unserved" ? "UB und LB gelten ausschließlich für die Nichtbedienung. Journey Time wird aus demselben Incumbent berechnet, aber nicht optimiert." : "UB und LB gelten für den kombinierten ganzzahligen Zielwert. Die daraus abgeleitete Bedienungsspanne wird separat gezeigt. Eine Journey-Time-LB erscheint erst, wenn die primäre Nichtbedienung durch diese Schranke feststeht."} {hasReference ? "Die gestrichelte All-Stop-Linie ist ein Vergleichswert und keine globale Schranke." : ""}</p>
      {detail.termination && <p className="greedy-note">Beendigung: <strong>{detail.termination.replaceAll("_", " ")}</strong></p>}
    </section>}
  </div>;
}
