import { useEffect, useMemo, useState } from "react";

type Attempt = { started_unix: number; finished_unix?: number; budget_seconds?: number };
type CalibrationJob = {
  id: string;
  group: "journey" | "oip";
  family: string;
  cabins: number;
  reference_kind: string;
  status: string;
  attempts: Attempt[];
};
type Campaign = {
  campaign_id: string;
  status: string;
  jobs: CalibrationJob[];
  execution_started_unix: number | null;
  deadline_unix?: number;
  finished_unix?: number;
  description?: string;
};
type Evidence = {
  job_id: string;
  capacity_proven: boolean;
  load_120?: number | null;
  latest_probe?: { demand: number; status: string; served?: number | null; served_upper_bound?: number | null; termination_reason?: string | null };
  proven_feasible_demand: number | null;
  proven_infeasible_demand: number | null;
};
type ReferenceIndex = { evidence: Evidence[]; current_probe?: { family: string; demand: number; served?: number | null; native_served?: number | null; served_upper_bound?: number | null; deadline_unix?: number; status?: string } | null };

const DATA_ROOT = "/generated/calibration";

function duration(seconds: number | null) {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const rounded = Math.max(0, Math.round(seconds));
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const rest = rounded % 60;
  return hours ? `${hours}h ${minutes}m` : minutes ? `${minutes}m ${rest}s` : `${rest}s`;
}

export default function CalibrationLivePage() {
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [references, setReferences] = useState<ReferenceIndex>({ evidence: [] });
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now() / 1000);

  useEffect(() => {
    let cancelled = false;
    setCampaign(null); setReferences({ evidence: [] }); setError(null);
    const dataRoot = DATA_ROOT;
    async function poll() {
      try {
        const stamp = Date.now();
        const [campaignResponse, referenceResponse] = await Promise.all([
          fetch(`${dataRoot}/campaign.json?t=${stamp}`, { cache: "no-store" }),
          fetch(`${dataRoot}/references.json?t=${stamp}`, { cache: "no-store" }),
        ]);
        if (!campaignResponse.ok || !referenceResponse.ok || !campaignResponse.headers.get("content-type")?.includes("application/json") || !referenceResponse.headers.get("content-type")?.includes("application/json")) throw new Error("Diese Kalibrierung wurde noch nicht vorbereitet oder ihre Live-Daten sind nicht verfügbar.");
        const [nextCampaign, nextReferences] = await Promise.all([
          campaignResponse.json() as Promise<Campaign>,
          referenceResponse.json() as Promise<ReferenceIndex>,
        ]);
        if (!cancelled) {
          setCampaign(nextCampaign);
          setReferences(nextReferences);
          setError(null);
          setNow(Date.now() / 1000);
        }
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Live files unavailable");
      }
    }
    poll();
    const timer = window.setInterval(poll, 2000);
    const clock = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => { cancelled = true; window.clearInterval(timer); window.clearInterval(clock); };
  }, []);

  const evidence = useMemo(
    () => new Map(references.evidence.map((item) => [item.job_id, item])),
    [references],
  );
  if (!campaign) return <main className="optimization-shell"><section className="optimization-empty">{error ?? "Loading calibration…"}</section></main>;
  const complete = campaign.jobs.filter((job) => job.status === "complete").length;
  const proven = references.evidence.filter((item) => item.capacity_proven).length;
  const running = campaign.jobs.find((job) => job.status === "running");
  const runningAttempt = running?.attempts.at(-1);
  const campaignElapsed = campaign.execution_started_unix == null ? null : (campaign.finished_unix ?? now) - campaign.execution_started_unix;
  const progress = 100 * complete / campaign.jobs.length;

  return <main className="optimization-shell calibration-live">
    <header className="optimization-hero">
      <div><p className="eyebrow">Thesis capacity calibration</p><h1>{campaign.jobs.length} reference runs</h1></div>
      <div className="campaign-status"><span className={`run-state run-state--${campaign.status}`}>{campaign.status}</span><strong>{complete}/{campaign.jobs.length}</strong></div>
    </header>
    {campaign.description && <section className="optimization-panel"><p>{campaign.description}</p><p>Regelmäßige All-Stop-Flotte mit frei optimierter gemeinsamer Phase. Nmax gilt nur für diese Referenzfamilie. 120 % werden erst nach dem Nachweis für N und N+1 freigegeben.</p></section>}
    {error && <div className="optimization-warning">Live connection: {error}. Showing the last valid state.</div>}
    <section className="calibration-summary">
      <article><span>Current job</span><strong>{running?.id ?? (campaign.status === "complete" ? "finished" : "—")}</strong><small>{runningAttempt ? duration(now - runningAttempt.started_unix) : ""}{running && references.current_probe ? ` · prüft N=${references.current_probe.demand}` : ""}</small></article>
      <article><span>Exact references</span><strong>{proven}</strong><small>validated N/N+1 brackets</small></article>
      <article><span>Campaign elapsed</span><strong>{duration(campaignElapsed)}</strong><small>{campaign.deadline_unix ? `${duration(campaign.deadline_unix - now)} remaining` : ""}</small></article>
    </section>
    <section className="optimization-panel">
      <div className="panel-heading"><h2>Overall progress</h2><span>{progress.toFixed(1)}%</span></div>
      <div className="calibration-progress"><span style={{ width: `${progress}%` }} /></div>
    </section>
    {(["journey", "oip"] as const).map((group) => {
      const jobs = campaign.jobs.filter((job) => job.group === group);
      if (!jobs.length) return null;
      return <section className="optimization-panel" key={group}>
        <div className="panel-heading"><h2>{group === "journey" ? "CAL-J · fixed balanced starts" : "CAL-O · free common phase"}</h2><span>{jobs.filter((job) => job.status === "complete").length}/{jobs.length}</span></div>
        <div className="calibration-table-wrap"><table className="calibration-table"><thead><tr><th>Family</th><th>K</th><th>Status</th><th>Proven feasible N</th><th>Proven infeasible</th><th>Letzte Prüfung</th><th>120 % von Nmax</th><th>Runtime</th></tr></thead><tbody>
          {jobs.map((job) => {
            const result = evidence.get(job.id);
            const attempt = job.attempts.at(-1);
            const elapsed = attempt ? (attempt.finished_unix ?? now) - attempt.started_unix : null;
            return <tr key={job.id} className={job.status === "running" ? "is-running" : undefined}>
              <td>{job.family.toUpperCase()}</td><td>{job.cabins}</td><td><span className={`run-state run-state--${job.status}`}>{job.status}</span></td>
              <td>{result?.proven_feasible_demand ?? "—"}</td><td>{result?.proven_infeasible_demand ?? "—"}</td><td>{result?.latest_probe ? `${result.latest_probe.demand}: ${result.latest_probe.status}` : "—"}</td><td>{result?.capacity_proven ? (result.load_120 ?? "—") : "—"}</td><td>{duration(elapsed)}</td>
            </tr>;
          })}
        </tbody></table></div>
      </section>;
    })}
  </main>;
}
