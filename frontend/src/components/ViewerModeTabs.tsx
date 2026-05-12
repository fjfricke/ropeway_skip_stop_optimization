import { BarChart3, LineChart, Network, PlayCircle } from "lucide-react";
import type { ViewerMode } from "./viewerTypes";

interface ViewerModeTabsProps {
  viewerMode: ViewerMode;
  onViewerModeChange: (mode: ViewerMode) => void;
}

export function ViewerModeTabs({ viewerMode, onViewerModeChange }: ViewerModeTabsProps) {
  return (
    <section className="toolbar toolbar--mode" aria-label="Viewer mode">
      <button className={viewerMode === "scenario" ? "is-active" : ""} onClick={() => onViewerModeChange("scenario")}>
        <Network size={17} />
        Scenario View
      </button>
      <button className={viewerMode === "graph" ? "is-active" : ""} onClick={() => onViewerModeChange("graph")}>
        <BarChart3 size={17} />
        Graph View
      </button>
      <button className={viewerMode === "metrics" ? "is-active" : ""} onClick={() => onViewerModeChange("metrics")}>
        <LineChart size={17} />
        Metrics View
      </button>
      <button className={viewerMode === "replay" ? "is-active" : ""} onClick={() => onViewerModeChange("replay")}>
        <PlayCircle size={17} />
        Replay View
      </button>
    </section>
  );
}
