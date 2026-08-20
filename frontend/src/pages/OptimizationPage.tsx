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
  return (
    <main className="optimization-shell">
      <header className="optimization-hero"><div><p className="eyebrow">Optimization Lab</p><h1>Certified fleet experiments</h1></div><p>Live DDD bounds, fixed-K campaigns and validated incumbents.</p></header>
      {error && <section className="optimization-empty">{error}. Start a sweep with <code>--frontend-live</code>.</section>}
      {!error && !index && <section className="optimization-empty">Loading campaigns…</section>}
      <section className="campaign-grid">
        {index?.campaigns.map((campaign) => (
          <AppLink className="campaign-card" href={`/optimization/${campaign.campaign_id}`} key={campaign.campaign_id}>
            <div className="campaign-card__top"><span className={`run-state run-state--${campaign.status ?? "queued"}`}>{campaign.status ?? "queued"}</span><span>seq {campaign.sequence ?? 0}</span></div>
            <h2>{campaign.label ?? campaign.campaign_id}</h2>
            <p>{campaign.objective ?? "objective pending"}</p>
            <div className="campaign-card__footer"><strong>{campaign.completed_trial_count ?? 0} / {campaign.trial_count ?? 0} trials</strong><span>{campaign.status === "running" ? "Open live details →" : "Open results →"}</span></div>
          </AppLink>
        ))}
      </section>
    </main>
  );
}
