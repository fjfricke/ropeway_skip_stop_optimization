import { AppLink } from "../App";
import type { OptimizationCampaignSnapshot } from "../optimizationTypes";

const number = (value?: number | null) => value == null ? "—" : value.toLocaleString("en-GB", { maximumFractionDigits: 1 });

export default function JourneyCampaignDashboard({ campaign }: { campaign: OptimizationCampaignSnapshot }) {
  const jobs = campaign.journey_jobs ?? [];
  return <>
    <section className="optimization-panel">
      <h2>Fixed starts · full service · minimum Journey Time</h2>
      <p>T5R/G500 · geometric headways · No-Wait. Demand: 1,464 s; service: 2,364 s; operation: 2,664 s.</p>
      <p>{jobs.filter(j => j.kind === "reference" && j.status !== "deferred").length} All-Stop calibrations, {jobs.filter(j => j.kind === "relative" && j.status !== "deferred").length} relative-load comparisons and {jobs.filter(j => j.kind === "constant" && j.status !== "deferred").length} constant-demand comparisons. The constant series uses half the K30 reference demand and requires certified All-Stop feasibility at K20, K25 and K30.</p>
      <p>Native incumbents are solver values; confirmed Journey Time is shown after independent validation. Missing values remain open.</p>
      {Object.entries(campaign.constant_gates ?? {}).map(([family, gate]) => <p key={family}>{family.toUpperCase()}: {gate.status.replaceAll("_", " ")} — {gate.reason}</p>)}
    </section>
    {([['reference', 'All-Stop calibration'], ['relative', 'Relative demand · 25% / 75%'], ['constant', 'Constant demand · 50% of K30']] as const).map(([kind, title]) => <section className="optimization-panel" key={kind}>
      <div className="panel-heading"><h2>{title}</h2><span>{jobs.filter(j => j.kind === kind && j.status === 'complete').length}/{jobs.filter(j => j.kind === kind && j.status !== 'deferred').length} finished</span></div>
      <div style={{ overflowX: 'auto' }}><table className="pattern-screening__table">
        <thead><tr><th>Case</th><th>K</th><th>Mode</th><th>{kind === 'reference' ? 'Feasible N' : 'Demand'}</th>{kind !== 'reference' && <><th>Native incumbent</th><th>Confirmed Journey Time</th><th>Lower bound</th><th>Gap</th></>}<th>Status</th><th>Progress</th></tr></thead>
        <tbody>{jobs.filter(j => j.kind === kind).map(job => <tr key={job.id}>
          <td>{job.family.toUpperCase()}{job.percent != null ? ` · ${job.percent}%` : ''}</td><td>{job.k}</td><td>{job.mode.replaceAll('_', ' ')}</td>
          <td>{number(kind === 'reference' ? job.capacity : job.demand)}</td>
          {kind !== 'reference' && <><td>{number(job.native_incumbent)}</td><td>{number(job.validated_objective)}</td><td>{number(job.lower_bound)}</td><td>{job.gap == null ? '—' : `${(job.gap * 100).toFixed(2)}%`}</td></>}
          <td title={job.reason}>{job.status.replaceAll('_', ' ')}{kind === 'reference' && job.capacity_proven ? ' · proven' : ''}{job.reason && <small style={{ display: 'block', maxWidth: '24rem' }}>{job.reason}</small>}</td>
          <td>{job.detail_url ? <AppLink href={job.detail_url}>Live details →</AppLink> : '—'}</td>
        </tr>)}</tbody>
      </table></div>
    </section>)}
  </>;
}
