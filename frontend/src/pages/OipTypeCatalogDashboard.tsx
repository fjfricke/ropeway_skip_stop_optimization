import { AppLink } from "../App";
import type { OptimizationCampaignSnapshot, OptimizationTrialSnapshot } from "../optimizationTypes";
import { optimizationStatusClass } from "../optimizationPresentation";
import "./oip-pattern-screening.css";

const fmt = (value: number | null | undefined, digits = 0) => value == null ? "—" : value.toLocaleString("de-DE", { maximumFractionDigits: digits });

export default function OipTypeCatalogDashboard({ campaign }: { campaign: OptimizationCampaignSnapshot }) {
  const trials = (Array.isArray(campaign.trials) ? campaign.trials : Object.values(campaign.trials)) as OptimizationTrialSnapshot[];
  const fixedMixes = trials.some(trial => trial.fixed_type_counts != null);
  const comparison = campaign.comparison_campaign;
  const sensitivity = campaign.study_variant === "fleet_sensitivity";
  const fleetValues = campaign.k_values?.join(" · ") ?? "—";
  const references = Object.entries(campaign.reference_runs ?? {}).sort(([a], [b]) => ["f2", "f3", "f0"].indexOf(a) - ["f2", "f3", "f0"].indexOf(b));
  const geometric = campaign.headway_contract === "geometric_shared_entry_exit_v1";
  return <div className="pattern-screening">
    <section className="optimization-panel pattern-screening__verdict">
      <div><p className="eyebrow">Gemeinsame OIP-Optimierung · No-Wait</p><h2>{fixedMixes ? "Feste Typmischungen · freie Positionen und Passagiere" : "Typen, Anfangspositionen, Zeiten und Passagiere gemeinsam"}</h2></div>
      <dl><div><dt>Läufe</dt><dd>{campaign.completed_trial_count ?? 0}/{campaign.trial_count ?? trials.length}</dd></div><div><dt>K</dt><dd>{fleetValues}</dd></div><div><dt>Waiting</dt><dd>nicht Teil der Reihe</dd></div></dl>
    </section>
    {sensitivity && <section className="optimization-panel">
      <div className="panel-heading"><div><p className="eyebrow">Flottensensitivität · K50 gegenüber K62</p><h2>Gleiche Nachfrage, zwölf Kabinen weniger</h2></div>
        {comparison && <AppLink href={`/optimization/${encodeURIComponent(comparison.campaign_id)}`}>Abgeschlossene K62-Reihe →</AppLink>}
      </div>
      <p>F2: 2.266 · F3: 5.430 · F0: 7.606 Personen. Dieselben Freigaben, OD-Verbindungen und Betriebsfenster wie bei K62; keine neue K50-Kalibrierung.</p>
      <p>Fünf Minuten je Mischung, ohne Fahrplanhint und ohne frühen Referenzabbruch. Der K50-All-Stop-Lauf ist die Kontrolle innerhalb dieser Reihe. K62-Werte dienen ausschließlich zum Vergleich; die Mischungsanteile sind auf ganze Kabinen angepasst.</p>
    </section>}
    {campaign.supplementary_phase_references && <PhaseReferences references={campaign.supplementary_phase_references} />}
    {references.length > 0 && <section className="optimization-panel">
      <div className="panel-heading"><div><p className="eyebrow">{fixedMixes ? "Gleiche Nachfrage · unabhängig geprüfter Vergleich" : "Gemeinsamer Startwert"}</p><h2>All-Stop-Referenzen</h2></div><span>Vor den Hauptläufen</span></div>
      <div className="table-scroll"><table className="pattern-screening__table"><thead><tr><th>Fall</th><th>Nachfrage</th><th>Bedient</th><th>Status</th></tr></thead><tbody>
        {references.map(([family, reference]) => <tr key={family}><td><strong>{family.toUpperCase()}</strong></td><td>{fmt(reference.demand_total)}</td><td>{fmt(reference.served)}</td><td><span className={`run-state run-state--${optimizationStatusClass(reference.status)}`}>{reference.status.replaceAll("_", " ")}</span></td></tr>)}
      </tbody></table></div>
    </section>}
    <section className="optimization-panel">
      <div className="panel-heading"><div><p className="eyebrow">{fixedMixes ? "Ohne Fahrplanhint · fünf Minuten je Mischung" : "Validierter All-Stop-Start bleibt erhalten"}</p><h2>{fixedMixes ? `${campaign.trial_count ?? trials.length}er-Mischungsreihe · ${geometric ? "geometrische Headways" : "historischer Vertrag"}` : "No-Wait-Hauptreihe"}</h2></div><span>UNKNOWN ist kein Unzulässigkeitsbeweis</span></div>
      <div className="table-scroll"><table className="pattern-screening__table"><thead><tr><th>K</th><th>Fall</th><th>Last</th><th>Formulierung</th><th>Nachfrage</th><th>Typen</th><th>{sensitivity ? "Bedient K50" : "Bedient"}</th>{comparison && <th>Bedient K62 · Vergleich</th>}<th>Journey Time · gemessen</th><th>Gap</th><th>Status</th><th></th></tr></thead><tbody>
        {trials.map(trial => <Row key={trial.trial_id} trial={trial} showComparison={!!comparison} comparisonTrial={comparison?.trials.find(item => item.trial_id === trial.comparison_trial_id)} />)}
      </tbody></table></div>
    </section>
  </div>;
}

function Row({ trial, comparisonTrial, showComparison }: { trial: OptimizationTrialSnapshot; comparisonTrial?: OptimizationTrialSnapshot; showComparison: boolean }) {
  const counts = trial.type_counts ?? trial.fixed_type_counts;
  const types = counts ? Object.entries(counts).filter(([, count]) => count > 0).map(([name, count]) => `${count}× ${name.replaceAll("_", " ")}`).join(" · ") : "—";
  return <tr>
    <td><strong>{trial.available_fleet_count}</strong></td><td>{(trial.family ?? "").toUpperCase()}</td><td>{trial.load ?? "—"}</td><td>{trial.formulation?.replaceAll("_", " ") ?? "—"}</td><td>{fmt(trial.demand_total)}</td>
    <td className="pattern-screening__patterns">{types}</td><td>{fmt(trial.served)}</td>
    {showComparison && <td>{fmt(comparisonTrial?.served)}{comparisonTrial?.run_campaign_id && <div><AppLink href={`/optimization/${encodeURIComponent(comparisonTrial.run_campaign_id)}`}>K62-Verlauf →</AppLink></div>}</td>}
    <td>{fmt(trial.journey_time_seconds, 1)}</td>
    <td>{trial.relative_gap == null ? "—" : `${fmt(100 * trial.relative_gap, 2)} %`}</td>
    <td><span className={`run-state run-state--${optimizationStatusClass(trial.status)}`}>{trial.solver_status === "FEASIBLE_CHECKPOINT" ? "Zulässig · gesichert" : trial.termination_reason === "WALL_DEADLINE" ? "Zeitlimit · kein geprüftes Ergebnis" : trial.termination_reason === "cannot_beat_reference" ? "Referenz nicht schlagbar" : (trial.status === "complete" && trial.solver_status ? trial.solver_status : trial.status.replaceAll("_", " "))}</span></td>
    <td>{trial.run_campaign_id ? <AppLink className="pattern-screening__link" href={`/optimization/${encodeURIComponent(trial.run_campaign_id)}`}>Live-Verlauf →</AppLink> : <span>—</span>}</td>
  </tr>;
}

export function PhaseReferences({ references }: { references: NonNullable<OptimizationCampaignSnapshot["supplementary_phase_references"]> }) {
  return <section className="optimization-panel">
    <div className="panel-heading"><div><p className="eyebrow">Ergänzender Vergleich · K50 · gleiche Nachfrage</p><h2>Regelmäßige All-Stop-Flotte · freie gemeinsame Phase</h2></div><span>{references.status.replaceAll("_", " ")}</span></div>
    <p>Drei zusätzliche Referenzbewertungen, je fünf Minuten. Keine neue Nmax-Kalibrierung. Die Anfangspositionen werden gemeinsam verschoben; die All-Stop-Kontrollläufe darüber hinaus erlauben freie Einzelpositionen. Die abgeschlossenen Mischungsergebnisse bleiben unverändert.</p>
    <div className="table-scroll"><table className="pattern-screening__table"><thead><tr><th>Fall</th><th>K</th><th>Nachfrage</th><th>Bedient</th><th>Obere Bedienungsschranke</th><th>Journey Time · gemessen</th><th>Status</th><th></th></tr></thead><tbody>
      {["f2", "f3", "f0"].map(family => {
        const r = references.reference_runs[family];
        if (!r) return null;
        return <tr key={family}><td>{family.toUpperCase()}</td><td>{r.fixed_k}</td><td>{fmt(r.demand_total)}</td><td>{fmt(r.served)}</td><td>{fmt(r.served_upper_bound)}</td><td>{fmt(r.journey_time_seconds, 1)}</td><td>{r.proven_optimal ? "Optimal für regelmäßige Flotte" : r.status === "complete" ? "Geprüfte Referenzlösung" : r.status.replaceAll("_", " ")}</td><td>{r.run_campaign_id && <AppLink href={`/optimization/${encodeURIComponent(r.run_campaign_id)}`}>Referenzdetails →</AppLink>}</td></tr>;
      })}
    </tbody></table></div>
    <p>Schranken gelten nur für die regelmäßige Flotte mit gemeinsamer Phase, nicht für freie Einzelpositionen oder andere Muster.</p>
  </section>;
}
