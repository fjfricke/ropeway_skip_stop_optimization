import { useMemo } from "react";
import { AppLink } from "../App";
import type { OptimizationCampaignSnapshot, OptimizationRefinementSnapshot, OptimizationTrialSnapshot } from "../optimizationTypes";
import { optimizationStatusClass } from "../optimizationPresentation";
import { Curve, progressColors, type Series } from "./GreedyProgressPanel";
import "./oip-pattern-screening.css";

const fmt = (value: number | null | undefined, digits = 0) =>
  value == null ? "—" : value.toLocaleString("de-DE", { maximumFractionDigits: digits });

const palette = [progressColors[0], progressColors[2], progressColors[3], "#9b6b43", "#667d58", "#8a667f"];

export default function OipPatternScreeningDashboard({ campaign }: { campaign: OptimizationCampaignSnapshot }) {
  const trials = Array.isArray(campaign.trials) ? campaign.trials : Object.values(campaign.trials);
  const refinements = campaign.refinements ?? [];
  const allocationOrder = campaign.allocation_order ?? [...new Set(trials.map((trial) => trial.allocation_id ?? trial.policy_id))];
  const kValues = campaign.k_values ?? [...new Set(trials.map((trial) => trial.available_fleet_count))].sort((a, b) => a - b);
  const charts = useMemo(() => ({
    service: buildSeries(trials, allocationOrder, "served"),
    journey: buildSeries(trials, allocationOrder, "journey_time_seconds"),
  }), [trials, allocationOrder]);
  const ordered = [...trials].sort((left, right) =>
    left.available_fleet_count - right.available_fleet_count
    || allocationOrder.indexOf(left.allocation_id ?? left.policy_id) - allocationOrder.indexOf(right.allocation_id ?? right.policy_id));
  const xMin = Math.min(...kValues);
  const xMax = Math.max(...kValues);

  return <div className="pattern-screening">
    <section className="optimization-panel pattern-screening__verdict">
      <div><p className="eyebrow">Thesis-Musterscreening · {(campaign.demand_family ?? "").toUpperCase()}</p><h2>Welche Muster tragen mit weniger Kabinen?</h2></div>
      <dl><div><dt>Nachfrage</dt><dd>{fmt(campaign.demand_total)}</dd></div><div><dt>Zeitfenster</dt><dd>{fmt(campaign.passenger_horizon_seconds)} s / {fmt(campaign.operation_seconds)} s</dd></div><div><dt>K-Werte</dt><dd>{kValues.join(" · ")}</dd></div></dl>
    </section>
    {refinements.length > 0 && <section className="optimization-panel">
      <div className="panel-heading"><div><p className="eyebrow">Gemeinsame CP-SAT-Nachoptimierung</p><h2>Bewegung und Passagiere wieder gemeinsam frei</h2></div><span>{campaign.completed_refinement_count ?? 0}/{campaign.refinement_count ?? refinements.length} abgeschlossen</span></div>
      <p className="greedy-note">Die Musterbelegung bleibt fest. Anfangspositionen, Ereigniszeiten und Passagierzuordnung werden gemeinsam optimiert; der Screeningplan ist nur ein Hint.</p>
      <div className="table-scroll"><table className="pattern-screening__table"><thead><tr><th>K</th><th>Belegung</th><th>Start bedient</th><th>Neu bedient</th><th>Start Journey</th><th>Neue Journey</th><th>Gap</th><th>Status</th><th></th></tr></thead><tbody>
        {refinements.map((trial) => <RefinementRow key={trial.refinement_id} trial={trial} />)}
      </tbody></table></div>
    </section>}
    <section className="optimization-panel">
      <div className="panel-heading"><div><p className="eyebrow">Unabhängig geprüft</p><h2>Bedienung und Journey Time nach Flottengröße</h2></div><span>Jeder Punkt gehört zu einem validierten Fahrplan</span></div>
      <div className="greedy-two-charts">
        <Curve series={charts.service} xMax={xMax} xLabel="Kabinen K" yLabel="Bediente Personen" />
        <Curve series={charts.journey} xMax={xMax} xLabel="Kabinen K" yLabel="Journey Time · Personen-s" zero={false} />
      </div>
      <p className="greedy-note">Die All-Stop-Kurve zeigt gefundene All-Stop-Fahrpläne, kein Referenzoptimum. Ungeklärte Bewegungen erzeugen keinen Nullpunkt.</p>
      <span className="pattern-screening__axis-note">Darstellungsbereich K={xMin}–{xMax}</span>
    </section>
    <section className="optimization-panel">
      <div className="panel-heading"><div><p className="eyebrow">Versuchsmatrix</p><h2>Muster, Bewegung und Passagierprüfung</h2></div><span>{campaign.completed_trial_count ?? 0}/{campaign.trial_count ?? trials.length} abgeschlossen</span></div>
      <div className="table-scroll"><table className="pattern-screening__table"><thead><tr><th>K</th><th>Belegung</th><th>Masken</th><th>Bewegung</th><th>Passagiere</th><th>Bedient</th><th>Journey Time</th><th>Zeit</th><th></th></tr></thead><tbody>
        {ordered.map((trial) => <ScreeningRow key={trial.trial_id} trial={trial} />)}
      </tbody></table></div>
    </section>
  </div>;
}

function RefinementRow({ trial }: { trial: OptimizationRefinementSnapshot }) {
  return <tr>
    <td><strong>{trial.available_fleet_count}</strong></td><td>{trial.allocation_label ?? trial.policy_id}</td>
    <td>{fmt(trial.source_served)}</td><td>{fmt(trial.served)}</td>
    <td>{fmt(trial.source_journey_time_seconds, 1)}</td><td>{fmt(trial.journey_time_seconds, 1)}</td>
    <td>{trial.relative_gap == null ? "—" : `${fmt(100 * trial.relative_gap, 2)} %`}</td>
    <td><span className={`run-state run-state--${optimizationStatusClass(trial.status)}`}>{trial.status.replaceAll("_", " ")}</span></td>
    <td>{trial.run_campaign_id ? <AppLink className="pattern-screening__link" href={`/optimization/${encodeURIComponent(trial.run_campaign_id)}`}>Verlauf →</AppLink> : <span>—</span>}</td>
  </tr>;
}

function buildSeries(trials: OptimizationTrialSnapshot[], order: string[], field: "served" | "journey_time_seconds"): Series[] {
  return order.map((allocationId, index) => {
    const matching = trials
      .filter((trial) => (trial.allocation_id ?? trial.policy_id) === allocationId && trial[field] != null)
      .sort((left, right) => left.available_fleet_count - right.available_fleet_count);
    const label = matching[0]?.allocation_label ?? allocationId.replaceAll("_", " ");
    return {
      name: label,
      color: palette[index % palette.length],
      dashed: allocationId === "all_stop",
      points: matching.map((trial) => ({ x: trial.available_fleet_count, y: trial[field]! })),
    };
  }).filter((series) => series.points.length > 0);
}

function ScreeningRow({ trial }: { trial: OptimizationTrialSnapshot }) {
  const movement = trial.movement_status ?? (trial.status === "complete" ? "unknown" : trial.status);
  const patterns = trial.pattern_composition
    ? Object.entries(trial.pattern_composition).map(([pattern, count]) => `${count}× ${pattern}`).join(" · ")
    : "—";
  const time = [trial.build_seconds, trial.solve_seconds, trial.passenger_build_seconds, trial.passenger_solve_seconds]
    .filter((value): value is number => value != null).reduce((sum, value) => sum + value, 0);
  return <tr>
    <td><strong>{trial.available_fleet_count}</strong></td><td>{trial.allocation_label ?? trial.policy_id}</td><td className="pattern-screening__patterns">{patterns}</td>
    <td><span className={`run-state run-state--${optimizationStatusClass(movement)}`}>{movement.replaceAll("_", " ")}</span></td>
    <td>{trial.passenger_status?.replaceAll("_", " ") ?? "—"}</td><td>{fmt(trial.served)}</td><td>{fmt(trial.journey_time_seconds, 1)}</td><td>{time ? `${fmt(time, 1)} s` : "—"}</td>
    <td>{trial.run_campaign_id ? <AppLink className="pattern-screening__link" href={`/optimization/${encodeURIComponent(trial.run_campaign_id)}`}>Fahrplan →</AppLink> : <span>—</span>}</td>
  </tr>;
}
