import { Suspense, useEffect, useState } from "react";
import type { ReactNode } from "react";
import ScenarioPage from "./pages/ScenarioPage";
import OptimizationCampaignPage from "./pages/OptimizationCampaignPage";
import OptimizationTrialPage from "./pages/OptimizationTrialPage";
import StudyOverview from "./pages/StudyOverview";
import StudyReferences from "./pages/StudyReferences";
import JourneyRunPage from "./pages/JourneyRunPage";





export default function App() {
  const [path, setPath] = useState(window.location.pathname + window.location.search);
  useEffect(() => {
    const update = () => setPath(window.location.pathname + window.location.search);
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  const parts = path.split("?")[0].split("/").filter(Boolean);
  const runId = new URLSearchParams(window.location.search).get("run");
  let page = <ScenarioPage key={path} />;
  if (parts[0] === "optimization" && parts.length === 1) page = <StudyOverview />;
  else if (parts[0] === "optimization" && parts.length === 2) page = <OptimizationCampaignPage campaignId={decodeURIComponent(parts[1])} />;
  else if (parts[0] === "optimization" && parts.length >= 4) page = <OptimizationTrialPage campaignId={decodeURIComponent(parts[1])} policyId={decodeURIComponent(parts[2])} fleetCount={Number(parts[3])} />;
  else if (parts[0] === "evolution-live" || parts[0] === "archive") page = <StudyOverview />;
  else if (parts[0] === "calibration-live") page = <StudyReferences key={path} />;

  else if (parts[0] === "thesis") page = runId ? <JourneyRunPage key={runId} id={runId} /> : <StudyOverview />;
  return <><nav className="app-nav"><AppLink href="/thesis">Campaigns</AppLink><AppLink href="/calibration-live">Calibrations & references</AppLink><AppLink href="/">Scenario Viewer</AppLink></nav><Suspense fallback={<main className="optimization-shell"><section className="optimization-empty">Loading view…</section></main>}>{page}</Suspense></>;
}

export function AppLink({ href, className, children }: { href: string; className?: string; children: ReactNode }) {
  return <a href={href} className={className} onClick={(event) => { if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); window.history.pushState({}, "", href); window.dispatchEvent(new PopStateEvent("popstate")); }}>{children}</a>;
}
