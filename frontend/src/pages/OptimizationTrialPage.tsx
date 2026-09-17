import { BoundProgressChart } from "../components/optimization/BoundProgressChart";
import { useOptimizationCampaign } from "../hooks/useOptimizationCampaign";
import {
  formatOptimizationDuration,
  formatOptimizationMemory,
  formatOptimizationNumber,
  isMovementFeasibilityCampaign,
  optimizationSemanticStatus,
  optimizationStatusClass,
} from "../optimizationPresentation";
import type { OptimizationFeasibilityAttempt, OptimizationTrialSnapshot } from "../optimizationTypes";
import { EventList } from "./OptimizationCampaignPage";

export default function OptimizationTrialPage({ campaignId, policyId, fleetCount }: { campaignId: string; policyId: string; fleetCount: number }) {
  const { campaign, error, stale } = useOptimizationCampaign(campaignId);
  const trials = campaign ? (Array.isArray(campaign.trials) ? campaign.trials : Object.values(campaign.trials)) : [];
  const trial = trials.find((item) => item.policy_id === policyId && item.available_fleet_count === fleetCount);
  if (!trial) return <main className="optimization-shell"><section className="optimization-empty">{error ?? "Loading trial…"}</section></main>;
  if (campaign && isMovementFeasibilityCampaign(campaign)) {
    return <FeasibilityTrial trial={trial} stale={stale} />;
  }
  if (trial.certificate_kind === "analytic_all_stop_capacity") {
    return <AnalyticInfeasibleTrial trial={trial} stale={stale} />;
  }
  const samples = trial.events.filter((event) => ["cg_round_completed", "solver_sample"].includes(event.kind) && event.global_certified_lower_bound != null);
  const usesSolverTime = samples.some((event) => event.kind === "solver_sample");
  const semanticStatus = optimizationSemanticStatus(trial);
  const continuation = campaign?.campaign_kind === "reservoir_cp_fleet_continuation";
  const isReservoir = campaign?.campaign_kind === "reservoir_arc_flow" || continuation;
  return <main className="optimization-shell"><header className="optimization-hero"><div><p className="eyebrow">Active trial{trial.formulation ? ` · ${trial.formulation.replaceAll("_", " ")}` : ""}</p><h1>{policyId} · {isReservoir ? "K≤" : "K="}{fleetCount}</h1></div><div className="campaign-status"><span className={`run-state run-state--${optimizationStatusClass(semanticStatus)}`}>{semanticStatus.replaceAll("_", " ")}</span>{stale && <span className="stale-badge">stale</span>}<strong>{usesSolverTime ? `${(trial.elapsed_seconds ?? 0).toFixed(0)}s` : `round ${trial.round_index ?? 0}`}</strong></div></header>{continuation ? <ContinuationMetrics trial={trial} /> : isReservoir ? <ReservoirMetrics trial={trial} /> : <section className="metric-strip"><Metric label="Certified LB" value={formatOptimizationNumber(trial.certified_lower_bound, 3)} /><Metric label="Validated UB" value={formatOptimizationNumber(trial.validated_upper_bound, 3)} /><Metric label="Global gap" value={trial.relative_gap == null ? "—" : `${(trial.relative_gap * 100).toFixed(3)}%`} /><Metric label="Elapsed" value={`${(trial.elapsed_seconds ?? 0).toFixed(1)}s`} /><Metric label="Stage" value={trial.stage ?? "between rounds"} /></section>}{trial.start_layout_kind && <section className="metric-strip"><Metric label="Start layout" value={trial.start_layout_kind.replaceAll("_", " ")} /><Metric label="K max AS" value={String(trial.all_stop_maximum_cabin_count ?? "—")} /><Metric label="Candidates" value={formatInteger(trial.start_layout_candidate_count)} /><Metric label="Served stations" value={formatInteger(trial.start_layout_service_station_count)} /><Metric label="Min station stops" value={formatInteger(trial.start_layout_minimum_station_stop_count)} /><Metric label="Max service gap" value={formatOptimizationDuration(trial.start_layout_maximum_service_gap_seconds)} /></section>}{!continuation && <section className="optimization-panel"><div className="panel-heading"><h2>{isReservoir ? "Unserved-passenger certificate" : "Global certificate timeline"}</h2><span>Only globally valid bounds are shown</span></div><BoundProgressChart xLabel={usesSolverTime ? "Elapsed seconds" : "CG round"} points={samples.map((event) => ({ x: usesSolverTime ? (event.elapsed_seconds ?? 0) : (event.round_index ?? 0), lower: event.global_certified_lower_bound!, upper: event.global_validated_upper_bound ?? null }))} /></section>}<section className="optimization-panel"><div className="panel-heading"><h2>Semantic event stream</h2><span>{trial.events.length} events</span></div><EventList events={trial.events.slice(-30).reverse()} /></section></main>;
}

function ContinuationMetrics({ trial }: { trial: OptimizationTrialSnapshot }) {
  return <><section className="metric-strip"><Metric label="Journey LB / UB" value={`${formatOptimizationNumber(trial.certified_lower_bound, 2)} / ${formatOptimizationNumber(trial.validated_upper_bound, 2)}`} /><Metric label="Served / unserved" value={`${formatInteger(trial.served)} / ${formatInteger(trial.unserved)}`} /><Metric label="Used fleet" value={formatInteger(trial.dispatched_fleet_count)} /><Metric label="Mean served journey" value={formatOptimizationDuration(trial.mean_served_journey_seconds)} /><Metric label="Improved seed" value={trial.native_strict_improvement == null ? "—" : trial.native_strict_improvement ? "yes" : "no"} /></section><section className="metric-strip"><Metric label="STOP / SKIP" value={`${formatInteger(trial.stop_count)} / ${formatInteger(trial.skip_count)}`} /><Metric label="Passenger-carrying SKIPs" value={formatInteger(trial.passenger_carrying_skip_count)} /><Metric label="Variables" value={formatInteger(trial.model_variable_count)} /><Metric label="Rows" value={formatInteger(trial.linear_constraint_count)} /><Metric label="Peak RSS" value={formatOptimizationMemory(trial.peak_rss_bytes)} /></section></>;
}

function ReservoirMetrics({ trial }: { trial: OptimizationTrialSnapshot }) {
  return <><section className="metric-strip"><Metric label="Unserved LB / UB" value={`${formatOptimizationNumber(trial.primary_lower_bound ?? trial.certified_lower_bound, 0)} / ${formatOptimizationNumber(trial.primary_upper_bound ?? trial.validated_upper_bound, 0)}`} /><Metric label="Served interval" value={`${formatOptimizationNumber(trial.served_lower_bound, 0)} – ${formatOptimizationNumber(trial.served_upper_bound, 0)}`} /><Metric label="Journey LB / UB" value={`${formatOptimizationNumber(trial.secondary_lower_bound, 0)} / ${formatOptimizationNumber(trial.secondary_upper_bound, 0)}`} /><Metric label="Used fleet" value={formatInteger(trial.dispatched_fleet_count)} /><Metric label="Stage" value={trial.stage ?? "between phases"} /></section><section className="metric-strip"><Metric label="Network N / A" value={`${formatInteger(trial.network_node_count)} / ${formatInteger(trial.network_arc_count)}`} /><Metric label="Movement vars" value={formatInteger(trial.movement_variable_count)} /><Metric label="Passenger vars" value={formatInteger(trial.passenger_variable_count)} /><Metric label="Rows" value={formatInteger(trial.linear_constraint_count)} /><Metric label="Peak RSS" value={trial.peak_rss_gb == null ? "—" : `${trial.peak_rss_gb.toFixed(1)} GB`} /></section></>;
}

function AnalyticInfeasibleTrial({ trial, stale }: { trial: OptimizationTrialSnapshot; stale: boolean }) {
  return <main className="optimization-shell"><header className="optimization-hero"><div><p className="eyebrow">Analytic movement certificate</p><h1>{trial.policy_id} · K={trial.available_fleet_count}</h1></div><div className="campaign-status"><span className="run-state run-state--infeasible">movement infeasible</span>{stale && <span className="stale-badge">stale</span>}<strong>solver not run</strong></div></header><div className="optimization-warning">{trial.detail ?? `K exceeds the certified all-stop capacity K_max_AS=${trial.all_stop_maximum_cabin_count ?? "—"}.`}</div><section className="metric-strip"><Metric label="Requested K" value={String(trial.available_fleet_count)} /><Metric label="K max AS" value={String(trial.all_stop_maximum_cabin_count ?? "—")} /><Metric label="Certificate" value="analytic all-stop capacity" /><Metric label="Solver time" value="0s" /></section><section className="optimization-panel"><div className="panel-heading"><h2>Semantic event stream</h2><span>{trial.events.length} events</span></div><EventList events={trial.events.slice(-30).reverse()} /></section></main>;
}

function FeasibilityTrial({ trial, stale }: { trial: OptimizationTrialSnapshot; stale: boolean }) {
  const semanticStatus = optimizationSemanticStatus(trial);
  const attempts = trial.events.flatMap((event) => {
    const value = event.payload?.feasibility_attempt;
    return isFeasibilityAttempt(value) ? [value] : [];
  });
  return (
    <main className="optimization-shell">
      <header className="optimization-hero">
        <div><p className="eyebrow">Canonical Fixed-K movement certificate</p><h1>{trial.policy_id} · K={trial.available_fleet_count}</h1></div>
        <div className="campaign-status"><span className={`run-state run-state--${optimizationStatusClass(semanticStatus)}`}>{semanticStatus.replaceAll("_", " ")}</span>{stale && <span className="stale-badge">stale</span>}<strong>{trial.termination?.replaceAll("_", " ") ?? trial.stage}</strong></div>
      </header>
      {trial.detail && <div className="optimization-warning">{trial.detail}</div>}
      <section className="metric-strip metric-strip--feasibility">
        <Metric label="CP time" value={formatOptimizationDuration(trial.cp_sat_seconds)} />
        <Metric label="Attempts" value={String(trial.attempt_count ?? (attempts.length || "—"))} />
        <Metric label="Native status" value={trial.cp_sat_solver_status_name ?? "—"} />
        <Metric label="Conflicts" value={formatInteger(trial.cp_sat_conflict_count)} />
        <Metric label="Branches" value={formatInteger(trial.cp_sat_branch_count)} />
        <Metric label="Peak RSS" value={formatOptimizationMemory(trial.peak_rss_bytes)} />
        <Metric label="Trajectories" value={formatInteger(trial.trajectory_count)} />
      </section>
      <section className="optimization-panel">
        <div className="panel-heading"><h2>Solver attempts</h2><span>Fresh worker process per attempt</span></div>
        <div className="feasibility-attempt-table" role="table" aria-label="CP-SAT feasibility attempts">
          <div className="feasibility-attempt-table__head" role="row"><span>Attempt</span><span>Verdict</span><span>Native</span><span>CP time</span><span>Branches</span><span>Memory</span></div>
          {attempts.map((attempt) => <div className="feasibility-attempt-table__row" role="row" key={attempt.attempt_index}><strong>#{attempt.attempt_index}</strong><span className={`run-state run-state--${optimizationStatusClass(attempt.status)}`}>{attempt.termination.replaceAll("_", " ")}</span><span>{attempt.cp_sat_solver_status_name ?? "—"}</span><span>{formatOptimizationDuration(attempt.cp_sat_seconds)}</span><span>{formatInteger(attempt.cp_sat_branch_count)}</span><span>{formatOptimizationMemory(attempt.peak_rss_bytes)}</span></div>)}
        </div>
      </section>
      <section className="optimization-panel"><div className="panel-heading"><h2>Semantic event stream</h2><span>{trial.events.length} events</span></div><EventList events={trial.events.slice(-30).reverse()} /></section>
    </main>
  );
}

function isFeasibilityAttempt(value: unknown): value is OptimizationFeasibilityAttempt {
  if (!value || typeof value !== "object") return false;
  const attempt = value as Partial<OptimizationFeasibilityAttempt>;
  return typeof attempt.cabin_count === "number" && typeof attempt.attempt_index === "number" && typeof attempt.status === "string" && typeof attempt.termination === "string";
}

function formatInteger(value: number | null | undefined) {
  return value == null ? "—" : value.toLocaleString();
}

function Metric({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div>; }
