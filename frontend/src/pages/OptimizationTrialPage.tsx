import { BoundProgressChart } from "../components/optimization/BoundProgressChart";
import { useOptimizationCampaign } from "../hooks/useOptimizationCampaign";
import { EventList } from "./OptimizationCampaignPage";

export default function OptimizationTrialPage({ campaignId, policyId, fleetCount }: { campaignId: string; policyId: string; fleetCount: number }) {
  const { campaign, error, stale } = useOptimizationCampaign(campaignId);
  const trials = campaign ? (Array.isArray(campaign.trials) ? campaign.trials : Object.values(campaign.trials)) : [];
  const trial = trials.find((item) => item.policy_id === policyId && item.available_fleet_count === fleetCount);
  if (!trial) return <main className="optimization-shell"><section className="optimization-empty">{error ?? "Loading trial…"}</section></main>;
  const rounds = trial.events.filter((event) => event.kind === "cg_round_completed" && event.global_certified_lower_bound != null);
  return <main className="optimization-shell"><header className="optimization-hero"><div><p className="eyebrow">Active trial</p><h1>{policyId} · K={fleetCount}</h1></div><div className="campaign-status"><span className={`run-state run-state--${trial.status}`}>{trial.status}</span>{stale && <span className="stale-badge">stale</span>}<strong>round {trial.round_index ?? 0}</strong></div></header><section className="metric-strip"><Metric label="Certified LB" value={number(trial.certified_lower_bound)} /><Metric label="Validated UB" value={number(trial.validated_upper_bound)} /><Metric label="Global gap" value={trial.relative_gap === undefined ? "—" : `${(trial.relative_gap * 100).toFixed(3)}%`} /><Metric label="Elapsed" value={`${(trial.elapsed_seconds ?? 0).toFixed(1)}s`} /><Metric label="Stage" value={trial.stage ?? "between rounds"} /></section><section className="optimization-panel"><div className="panel-heading"><h2>Global certificate timeline</h2><span>Local pricing bounds are intentionally excluded</span></div><BoundProgressChart xLabel="CG round" points={rounds.map((event) => ({ x: event.round_index ?? 0, lower: event.global_certified_lower_bound!, upper: event.global_validated_upper_bound ?? null }))} /></section><section className="optimization-panel"><div className="panel-heading"><h2>Semantic event stream</h2><span>{trial.events.length} events</span></div><EventList events={trial.events.slice(-30).reverse()} /></section></main>;
}

function Metric({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div>; }
function number(value: number | undefined) { return value === undefined ? "—" : value.toFixed(3); }
