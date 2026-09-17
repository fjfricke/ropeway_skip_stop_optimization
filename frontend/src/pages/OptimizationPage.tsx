import { useEffect, useState } from "react";
import type { OptimizationCampaignIndex } from "../optimizationTypes";
import { AppLink } from "../App";

export default function OptimizationPage() {
  const [index, setIndex] = useState<OptimizationCampaignIndex | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    async function poll() {
      try {
        const response = await fetch(
          `/generated/optimization/index.json?t=${Date.now()}`,
          { cache: "no-store" },
        );
        if (!response.ok) throw new Error(`Optimization index: HTTP ${response.status}`);
        const value = (await response.json()) as OptimizationCampaignIndex;
        if (cancelled) return;
        setIndex(value);
        setError(null);
        if (value.campaigns.some((campaign) => campaign.status === "running")) {
          timer = window.setTimeout(poll, 1000);
        }
      } catch (cause) {
        if (cancelled) return;
        setError(cause instanceof Error ? cause.message : "Index unavailable");
        timer = window.setTimeout(poll, 2000);
      }
    }

    poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);
  const campaigns = index?.campaigns.filter(
    (campaign) => campaign.study_membership === "current_thesis",
  ) ?? [];
  return (
    <main className="optimization-shell">
      <header className="optimization-hero"><div><p className="eyebrow">Current thesis runs</p><h1>Comparable optimization evidence</h1></div><p>Only campaigns that explicitly declare the current frozen thesis contract appear here.</p></header>
      {error && <section className="optimization-empty">{error}. Start a sweep with <code>--frontend-live</code>.</section>}
      {!error && !index && <section className="optimization-empty">Loading campaigns…</section>}
      {index && campaigns.length === 0 && <section className="optimization-empty">No campaign for the current thesis contract has been published yet. Historical and exploratory runs remain available in the archive.</section>}
      <section className="campaign-grid">
        {campaigns.map((campaign) => (
          <AppLink className="campaign-card" href={`/optimization/${campaign.campaign_id}`} key={campaign.campaign_id}>
            <div className="campaign-card__top"><span className={`run-state run-state--${campaign.status ?? "queued"}`}>{campaign.status ?? "queued"}</span><span>seq {campaign.sequence ?? 0}</span></div>
            <h2>{campaign.label ?? campaign.campaign_id}</h2>
            <p>{campaign.objective ?? "objective pending"}</p>
            <div className="campaign-card__footer">
              <strong>
                {campaign.campaign_kind === "movement_feasibility"
                  ? campaign.largest_certified_feasible_k != null
                    ? `Feasible through K=${campaign.largest_certified_feasible_k}`
                    : `${campaign.completed_trial_count ?? 0} values tested`
                  : `${campaign.completed_trial_count ?? 0} / ${campaign.trial_count ?? 0} trials`}
              </strong>
              <span>
                {campaign.campaign_kind === "movement_feasibility" && campaign.frontier_k != null
                  ? `Frontier K=${campaign.frontier_k}: ${campaign.frontier_status ?? "unknown"} →`
                  : campaign.status === "running" ? "Open live details →" : "Open results →"}
              </span>
            </div>
          </AppLink>
        ))}
      </section>
    </main>
  );
}
