import { BarChart3, GitBranch, LineChart, Network, PlayCircle, RadioTower } from "lucide-react";
import type { AvailableViewerModes, ViewerMode } from "./viewerTypes";

interface ViewerModeTabsProps {
  viewerMode: ViewerMode;
  availableModes: AvailableViewerModes;
  onViewerModeChange: (mode: ViewerMode) => void;
}

export function ViewerModeTabs({ viewerMode, availableModes, onViewerModeChange }: ViewerModeTabsProps) {
  return (
    <section className="toolbar toolbar--mode" aria-label="Viewer mode">
      <div className="toolbar__row" aria-label="Physical and discrete views">
        <button className={viewerMode === "scenario" ? "is-active" : ""} onClick={() => onViewerModeChange("scenario")}>
          <Network size={17} />
          Scenario View
        </button>
        {availableModes.graph ? (
          <button className={viewerMode === "graph" ? "is-active" : ""} onClick={() => onViewerModeChange("graph")}>
            <BarChart3 size={17} />
            Discrete Graph
          </button>
        ) : null}
        {availableModes.metrics ? (
          <button className={viewerMode === "metrics" ? "is-active" : ""} onClick={() => onViewerModeChange("metrics")}>
            <LineChart size={17} />
            Discrete Metrics
          </button>
        ) : null}
        {availableModes.replay ? (
          <button className={viewerMode === "replay" ? "is-active" : ""} onClick={() => onViewerModeChange("replay")}>
            <PlayCircle size={17} />
            Discrete Replay
          </button>
        ) : null}
      </div>

      {availableModes.ean || availableModes.ean_metrics || availableModes.ean_replay ? (
        <div className="toolbar__row toolbar__row--ean" aria-label="EAN views">
          {availableModes.ean ? (
            <button className={viewerMode === "ean" ? "is-active" : ""} onClick={() => onViewerModeChange("ean")}>
              <GitBranch size={17} />
              EAN View
            </button>
          ) : null}
          {availableModes.ean_metrics ? (
            <button className={viewerMode === "ean_metrics" ? "is-active" : ""} onClick={() => onViewerModeChange("ean_metrics")}>
              <LineChart size={17} />
              EAN Metrics
            </button>
          ) : null}
          {availableModes.ean_replay ? (
            <button className={viewerMode === "ean_replay" ? "is-active" : ""} onClick={() => onViewerModeChange("ean_replay")}>
              <RadioTower size={17} />
              EAN Replay
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
