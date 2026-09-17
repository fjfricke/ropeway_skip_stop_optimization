import { useEffect, useState } from "react";
import { AppLink } from "../App";
import type { OptimizationCampaignIndex } from "../optimizationTypes";

export default function ArchivePage() {
  const [index, setIndex] = useState<OptimizationCampaignIndex | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    fetch(`/generated/optimization/index.json?t=${Date.now()}`, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json() as Promise<OptimizationCampaignIndex>;
      })
      .then(setIndex)
      .catch((cause) => setError(cause instanceof Error ? cause.message : "Archive unavailable"));
  }, []);
  const campaigns = index?.campaigns.filter(
    (campaign) => campaign.study_membership !== "current_thesis",
  ) ?? [];
  return <main className="optimization-shell">
    <header className="optimization-hero"><div><p className="eyebrow">Research archive</p><h1>Historical and exploratory runs</h1></div><p>These records retain their original contracts. They are available for provenance and are not presented as current thesis evidence.</p></header>
    <section className="archive-shortcuts">
      <AppLink className="campaign-card" href="/evolution-live"><h2>Evolution diagnostics</h2><p>Candidate histories, repairs and conflict traces.</p></AppLink>
    </section>
    {error && <section className="optimization-empty">{error}</section>}
    {!error && !index && <section className="optimization-empty">Loading archive…</section>}
    <section className="campaign-grid">
      {campaigns.map((campaign) => <AppLink className="campaign-card" href={`/optimization/${campaign.campaign_id}`} key={campaign.campaign_id}>
        <div className="campaign-card__top"><span className="run-state">archived contract</span><span>{campaign.status ?? "unknown"}</span></div>
        <h2>{campaign.label ?? campaign.campaign_id}</h2>
        <p>{campaign.objective ?? "Objective not recorded"}</p>
      </AppLink>)}
    </section>
  </main>;
}
