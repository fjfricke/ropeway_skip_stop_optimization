import { BoundProgressChart } from "../components/optimization/BoundProgressChart";
import { useOptimizationCampaign } from "../hooks/useOptimizationCampaign";
import type { OptimizationTrialSnapshot } from "../optimizationTypes";
import { AppLink } from "../App";

export default function OptimizationCampaignPage({ campaignId }: { campaignId: string }) {
  const { campaign, error, stale } = useOptimizationCampaign(campaignId);
  if (!campaign) return <main className="optimization-shell"><section className="optimization-empty">{error ?? "Loading campaign…"}</section></main>;
  const trials = Array.isArray(campaign.trials) ? campaign.trials : Object.values(campaign.trials);
  const policies = campaign.policies ? Object.values(campaign.policies) : [];
  return (
    <main className="optimization-shell">
      <header className="optimization-hero"><div><p className="eyebrow">Campaign</p><h1>{campaign.label ?? campaign.campaign_id}</h1></div><div className="campaign-status"><span className={`run-state run-state--${campaign.status}`}>{campaign.status}</span>{stale && <span className="stale-badge">No update for 15s</span>}<strong>{campaign.completed_trial_count ?? 0}/{campaign.trial_count ?? trials.length}</strong></div></header>
      {error && <div className="optimization-warning">Live connection: {error}. Showing the last valid snapshot.</div>}
      <section className="optimization-panel"><div className="panel-heading"><h2>Policy × fleet size</h2><span>Global certificates only</span></div><div className="trial-matrix">{trials.map((trial) => <TrialCell key={trial.trial_id} campaignId={campaignId} trial={trial} />)}</div></section>
      {policies.map((policy) => <section className="optimization-panel" key={policy.policy.id}><div className="panel-heading"><h2>{policy.policy.label}</h2><span>{policy.policy.example_id}</span></div><BoundProgressChart points={policy.bounds.map((point) => ({ x: point.available_fleet_count, lower: point.tightened_lower_bound, upper: point.tightened_upper_bound }))} /></section>)}
      <section className="optimization-panel"><div className="panel-heading"><h2>Recent events</h2><span>seq {campaign.sequence}</span></div><EventList events={(campaign.events ?? []).slice(-12).reverse()} /></section>
    </main>
  );
}

function TrialCell({ campaignId, trial }: { campaignId: string; trial: OptimizationTrialSnapshot }) {
  return <AppLink className="trial-cell" href={`/optimization/${campaignId}/${trial.policy_id}/${trial.available_fleet_count}`}><div><strong>{trial.policy_id}</strong><span>K={trial.available_fleet_count}</span></div><span className={`run-state run-state--${trial.status}`}>{trial.status}</span><dl><dt>LB</dt><dd>{format(trial.certified_lower_bound)}</dd><dt>UB</dt><dd>{format(trial.validated_upper_bound)}</dd><dt>Gap</dt><dd>{trial.relative_gap === undefined ? "—" : `${(trial.relative_gap * 100).toFixed(2)}%`}</dd></dl></AppLink>;
}

export function EventList({ events }: { events: Array<{ sequence: number; kind: string; timestamp_utc: string; round_index?: number | null }> }) {
  return <ol className="event-list">{events.map((event) => <li key={event.sequence}><time>{new Date(event.timestamp_utc).toLocaleTimeString()}</time><strong>{event.kind.replaceAll("_", " ")}</strong><span>{event.round_index == null ? "" : `round ${event.round_index}`}</span></li>)}</ol>;
}

function format(value: number | undefined) { return value === undefined ? "—" : value.toFixed(2); }
