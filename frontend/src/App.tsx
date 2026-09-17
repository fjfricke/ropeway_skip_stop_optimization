import { lazy, Suspense, useEffect, useState } from "react";
import type { ReactNode } from "react";
import ScenarioPage from "./pages/ScenarioPage";
import OptimizationPage from "./pages/OptimizationPage";
import OptimizationCampaignPage from "./pages/OptimizationCampaignPage";
import OptimizationTrialPage from "./pages/OptimizationTrialPage";
import ThesisPage from "./pages/ThesisPage";

const EvolutionLivePage = lazy(() => import("./pages/EvolutionLivePage"));
const CalibrationLivePage = lazy(() => import("./pages/CalibrationLivePage"));
const ArchivePage = lazy(() => import("./pages/ArchivePage"));

export default function App() {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => {
    const update = () => setPath(window.location.pathname);
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  const parts = path.split("/").filter(Boolean);
  let page = <ScenarioPage />;
  if (parts[0] === "optimization" && parts.length === 1) page = <OptimizationPage />;
  else if (parts[0] === "optimization" && parts.length === 2) page = <OptimizationCampaignPage campaignId={decodeURIComponent(parts[1])} />;
  else if (parts[0] === "optimization" && parts.length >= 4) page = <OptimizationTrialPage campaignId={decodeURIComponent(parts[1])} policyId={decodeURIComponent(parts[2])} fleetCount={Number(parts[3])} />;
  else if (parts[0] === "evolution-live") page = <EvolutionLivePage />;
  else if (parts[0] === "calibration-live") page = <CalibrationLivePage />;
  else if (parts[0] === "archive") page = <ArchivePage />;
  else if (parts[0] === "thesis") page = <ThesisPage />;
  return <><nav className="app-nav"><AppLink href="/thesis">Thesis Atlas</AppLink><AppLink href="/optimization">Thesis runs</AppLink><AppLink href="/calibration-live">Calibration live</AppLink><AppLink href="/">Scenario Viewer</AppLink><AppLink href="/archive">Archive</AppLink></nav><Suspense fallback={<main className="optimization-shell"><section className="optimization-empty">Loading view…</section></main>}>{page}</Suspense></>;
}

export function AppLink({ href, className, children }: { href: string; className?: string; children: ReactNode }) {
  return <a href={href} className={className} onClick={(event) => { if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); window.history.pushState({}, "", href); window.dispatchEvent(new PopStateEvent("popstate")); }}>{children}</a>;
}
