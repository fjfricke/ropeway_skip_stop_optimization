import { AppLink } from "../App";
import { BoundProgressChart } from "../components/optimization/BoundProgressChart";
import { useOptimizationCampaign } from "../hooks/useOptimizationCampaign";
import {
  formatOptimizationDuration,
  formatOptimizationNumber,
  isMovementFeasibilityCampaign,
  optimizationSemanticStatus,
  optimizationStatusClass,
} from "../optimizationPresentation";
import type { OptimizationEvent, OptimizationTrialSnapshot } from "../optimizationTypes";
import JourneyCampaignDashboard from "./JourneyCampaignDashboard";
import FleetContinuationDashboard from "./FleetContinuationDashboard";
import ThesisOverloadDashboard from "./ThesisOverloadDashboard";
import OipPatternScreeningDashboard from "./OipPatternScreeningDashboard";
import OipTypeCatalogDashboard from "./OipTypeCatalogDashboard";

export default function OptimizationCampaignPage({ campaignId }: { campaignId: string }) {
  const { campaign, error, stale } = useOptimizationCampaign(campaignId);
  if (!campaign) {
    return <main className="optimization-shell"><section className="optimization-empty">{error ?? "Loading campaign…"}</section></main>;
  }
  const trials = Array.isArray(campaign.trials) ? campaign.trials : Object.values(campaign.trials);
  const policies = campaign.policies ? Object.values(campaign.policies) : [];
  const feasibility = isMovementFeasibilityCampaign(campaign);
  const continuation = campaign.campaign_kind === "reservoir_cp_fleet_continuation";
  const overload = campaign.campaign_kind === "thesis_full_cp_sat_overload" || campaign.campaign_kind === "oip_comparison";
  const patternScreening = campaign.campaign_kind === "oip_pattern_screening";
  const journey = campaign.campaign_kind === "journey_comparison";
  const typeCatalog = campaign.campaign_kind === "oip_type_catalog";
  return (
    <main className="optimization-shell">
      <header className="optimization-hero">
        <div><p className="eyebrow">{feasibility ? "Movement feasibility" : continuation ? "Fleet continuation" : "Campaign"}</p><h1>{campaign.label ?? campaign.campaign_id}</h1></div>
        <div className="campaign-status">
          <span className={`run-state run-state--${campaign.status}`}>{campaign.status.replaceAll("_", " ")}</span>
          {stale && <span className="stale-badge">{overload ? "No new solver event for 15s" : "No update for 15s"}</span>}
          <strong>{feasibility ? `certified through K=${campaign.largest_certified_feasible_k ?? "—"}` : `${campaign.completed_trial_count ?? 0}/${campaign.trial_count ?? trials.length}`}</strong>
        </div>
      </header>
      {error && <div className="optimization-warning">Live connection: {error}. Showing the last valid snapshot.</div>}
      {continuation && <FleetContinuationDashboard campaignId={campaignId} />}
      {overload && <ThesisOverloadDashboard campaignId={campaignId} />}
      {patternScreening && <OipPatternScreeningDashboard campaign={campaign} />}
      {typeCatalog && <OipTypeCatalogDashboard campaign={campaign} />}
      {journey && <JourneyCampaignDashboard campaign={campaign} />}
      {feasibility && campaign.frontier_k != null && (
        <section className="feasibility-verdict" aria-label="Feasibility frontier">
          <div><span>Largest certified feasible fleet</span><strong>K={campaign.largest_certified_feasible_k ?? "—"}</strong></div>
          <div><span>Frontier probe</span><strong>K={campaign.frontier_k}</strong><small>{(campaign.frontier_termination ?? campaign.frontier_status ?? "unknown").replaceAll("_", " ")}</small></div>
          <p>Each verdict applies to the documented canonical Fixed-K starts. UNKNOWN is not an infeasibility certificate.</p>
        </section>
      )}
      {!continuation && !overload && !patternScreening && !typeCatalog && !journey && <section className="optimization-panel">
        <div className="panel-heading"><h2>{feasibility ? "Exact-K feasibility probes" : continuation ? "Progressive fleet caps" : "Policy × fleet size"}</h2><span>{feasibility ? `${trials.length} tested fleet sizes` : continuation ? "Each bound belongs to its displayed K" : "Global certificates only"}</span></div>
        <div className="trial-matrix">{trials.map((trial) => <TrialCell key={trial.trial_id} campaignId={campaignId} trial={trial} feasibility={feasibility} continuation={continuation} />)}</div>
      </section>}
      {!feasibility && !continuation && !overload && !patternScreening && !typeCatalog && !journey && policies.map((policy) => <section className="optimization-panel" key={policy.policy.id}><div className="panel-heading"><h2>{policy.policy.label}</h2><span>{policy.policy.example_id}</span></div><BoundProgressChart points={policy.bounds.map((point) => ({ x: point.available_fleet_count, lower: point.tightened_lower_bound, upper: point.tightened_upper_bound }))} /></section>)}
      {!overload && !patternScreening && !typeCatalog && !journey && <section className="optimization-panel"><div className="panel-heading"><h2>Recent events</h2><span>seq {campaign.sequence}</span></div><EventList events={(campaign.events ?? []).slice(-12).reverse()} /></section>}
    </main>
  );
}

function TrialCell({ campaignId, trial, feasibility, continuation }: { campaignId: string; trial: OptimizationTrialSnapshot; feasibility: boolean; continuation: boolean }) {
  const semanticStatus = optimizationSemanticStatus(trial);
  return (
    <AppLink className="trial-cell" href={`/optimization/${campaignId}/${trial.policy_id}/${trial.available_fleet_count}`}>
      <div><strong>{trial.policy_id}</strong><span>K={trial.available_fleet_count}</span></div>
      <span className={`run-state run-state--${optimizationStatusClass(semanticStatus)}`}>{semanticStatus.replaceAll("_", " ")}</span>
      {feasibility ? (
        <dl><dt>CP time</dt><dd>{formatOptimizationDuration(trial.cp_sat_seconds)}</dd><dt>Attempts</dt><dd>{trial.attempt_count ?? "—"}</dd><dt>Trajectories</dt><dd>{trial.trajectory_count ?? "—"}</dd></dl>
      ) : continuation ? (
        <dl><dt>Journey objective</dt><dd>{formatOptimizationNumber(trial.validated_upper_bound, 2)}</dd><dt>Served</dt><dd>{formatOptimizationNumber(trial.served, 0)}</dd><dt>Used K</dt><dd>{trial.dispatched_fleet_count ?? "—"}</dd></dl>
      ) : trial.certificate_kind === "analytic_all_stop_capacity" ? (
        <dl><dt>Certificate</dt><dd>analytic</dd><dt>Limit</dt><dd>K≤{trial.all_stop_maximum_cabin_count ?? "—"}</dd><dt>Solver</dt><dd>not run</dd></dl>
      ) : (
        <dl><dt>LB</dt><dd>{formatOptimizationNumber(trial.certified_lower_bound, 2)}</dd><dt>UB</dt><dd>{formatOptimizationNumber(trial.validated_upper_bound, 2)}</dd><dt>Gap</dt><dd>{trial.relative_gap == null ? "—" : `${(trial.relative_gap * 100).toFixed(2)}%`}</dd></dl>
      )}
    </AppLink>
  );
}

export function EventList({ events }: { events: OptimizationEvent[] }) {
  return <ol className="event-list">{events.map((event) => {
    const feasibility = event.payload?.method === "fixed_k_cp_sat_feasibility";
    return <li key={event.sequence}><time>{new Date(event.timestamp_utc).toLocaleTimeString()}</time><strong>{event.kind.replaceAll("_", " ")}</strong><span>{event.round_index == null ? "" : `${feasibility ? "attempt" : "round"} ${event.round_index}`}</span></li>;
  })}</ol>;
}
