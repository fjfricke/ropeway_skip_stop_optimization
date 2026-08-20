import { useEffect, useRef, useState } from "react";
import type { OptimizationCampaignSnapshot } from "../optimizationTypes";

export function useOptimizationCampaign(campaignId: string | undefined) {
  const [campaign, setCampaign] = useState<OptimizationCampaignSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const latestSequence = useRef(-1);

  useEffect(() => {
    if (!campaignId) return;
    let cancelled = false;
    let timer: number | undefined;

    async function poll() {
      try {
        const response = await fetch(
          `/generated/optimization/${encodeURIComponent(campaignId!)}/snapshot.json?t=${Date.now()}`,
          { cache: "no-store" },
        );
        if (!response.ok) throw new Error(`Campaign snapshot: HTTP ${response.status}`);
        const value = (await response.json()) as OptimizationCampaignSnapshot;
        if (!cancelled && value.sequence >= latestSequence.current) {
          latestSequence.current = value.sequence;
          setCampaign(value);
          setError(null);
        }
        if (!cancelled && !["complete", "failed", "interrupted"].includes(value.status)) {
          timer = window.setTimeout(poll, 1000);
        }
      } catch (cause) {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : "Snapshot unavailable");
          timer = window.setTimeout(poll, 2000);
        }
      }
    }

    poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [campaignId]);

  const stale = campaign?.updated_at_utc
    ? Date.now() - Date.parse(campaign.updated_at_utc) > 15_000 && campaign.status === "running"
    : false;
  return { campaign, error, stale };
}
