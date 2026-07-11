import { Activity, BarChart3, GitBranch, LineChart, Network, PlayCircle, RadioTower } from "lucide-react";
import type { ExportArtifactSetBackend } from "../types";
import type { AvailableViewerModes, ViewerMode } from "./viewerTypes";

interface ViewerModeTabsProps {
  viewerMode: ViewerMode;
  selectedBackend: ExportArtifactSetBackend;
  hasOptimizationModes: boolean;
  onScenarioModeChange: () => void;
  onOptimizationModeChange: () => void;
}

interface OptimizationModeTabsProps {
  viewerMode: ViewerMode;
  selectedBackend: ExportArtifactSetBackend;
  availableModes: AvailableViewerModes;
  onViewerModeChange: (mode: ViewerMode) => void;
}

export function ViewerModeTabs({
  viewerMode,
  selectedBackend,
  hasOptimizationModes,
  onScenarioModeChange,
  onOptimizationModeChange,
}: ViewerModeTabsProps) {
  const optimizationLabel = selectedBackend === "ean" ? "Optimization (EAN)" : "Optimization (discrete)";
  const isOptimizationActive = viewerMode !== "scenario";

  return (
    <section className="toolbar toolbar--mode" aria-label="Viewer mode">
      <div className="toolbar__row" aria-label="Viewer areas">
        <button className={viewerMode === "scenario" ? "is-active" : ""} onClick={onScenarioModeChange}>
          <Network size={17} />
          Scenario
        </button>
        {selectedBackend === "discrete" || selectedBackend === "ean" ? (
          <button
            className={isOptimizationActive ? "is-active" : ""}
            disabled={!hasOptimizationModes}
            onClick={onOptimizationModeChange}
          >
            <GitBranch size={17} />
            {optimizationLabel}
          </button>
        ) : null}
      </div>
    </section>
  );
}

export function OptimizationModeTabs({ viewerMode, selectedBackend, availableModes, onViewerModeChange }: OptimizationModeTabsProps) {
  if (selectedBackend === "ean") {
    return (
      <div className="toolbar__view-toggle" aria-label="EAN optimization views">
        {availableModes.ean ? (
          <button className={viewerMode === "ean" ? "is-active" : ""} onClick={() => onViewerModeChange("ean")}>
            <GitBranch size={17} />
            View
          </button>
        ) : null}
        {availableModes.ean_progress ? (
          <button className={viewerMode === "ean_progress" ? "is-active" : ""} onClick={() => onViewerModeChange("ean_progress")}>
            <Activity size={17} />
            Progress
          </button>
        ) : null}
        {availableModes.ean_metrics ? (
          <button className={viewerMode === "ean_metrics" ? "is-active" : ""} onClick={() => onViewerModeChange("ean_metrics")}>
            <LineChart size={17} />
            Metrics
          </button>
        ) : null}
        {availableModes.ean_replay ? (
          <button className={viewerMode === "ean_replay" ? "is-active" : ""} onClick={() => onViewerModeChange("ean_replay")}>
            <RadioTower size={17} />
            Replay
          </button>
        ) : null}
      </div>
    );
  }

  return (
    <div className="toolbar__view-toggle" aria-label="Discrete optimization views">
      {availableModes.graph ? (
        <button className={viewerMode === "graph" ? "is-active" : ""} onClick={() => onViewerModeChange("graph")}>
          <BarChart3 size={17} />
          Graph
        </button>
      ) : null}
      {availableModes.metrics ? (
        <button className={viewerMode === "metrics" ? "is-active" : ""} onClick={() => onViewerModeChange("metrics")}>
          <LineChart size={17} />
          Metrics
        </button>
      ) : null}
      {availableModes.replay ? (
        <button className={viewerMode === "replay" ? "is-active" : ""} onClick={() => onViewerModeChange("replay")}>
          <PlayCircle size={17} />
          Replay
        </button>
      ) : null}
    </div>
  );
}
