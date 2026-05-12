import { useMemo, useState } from "react";
import { DiscreteOverlayToolbar } from "./DiscreteOverlayToolbar";
import { GraphSlackView } from "./GraphSlackView";
import { MetricsView } from "./MetricsView";
import { ReplayView } from "./ReplayView";
import { ScenarioToolbar } from "./ScenarioToolbar";
import { ScenarioView } from "./ScenarioView";
import { ViewerHeader } from "./ViewerHeader";
import { ViewerModeTabs } from "./ViewerModeTabs";
import type {
  ArtifactSelectionControl,
  DiscreteOverlayMode,
  DiscreteViewerToggles,
  ViewerMode,
  ViewerToggles,
} from "./viewerTypes";
import type { DiscreteScenario, MovementPlan, PassengerReplayResult, ReplayMetrics, Scenario, Selection } from "../types";

interface ScenarioViewerProps {
  scenario: Scenario;
  discreteScenario: DiscreteScenario | null;
  movementPlan: MovementPlan | null;
  passengerReplay: PassengerReplayResult | null;
  replayMetrics: ReplayMetrics | null;
  discreteWarning: string | null;
  movementPlanWarning: string | null;
  passengerReplayWarning: string | null;
  replayMetricsWarning: string | null;
  artifactSelection: ArtifactSelectionControl;
}

export function ScenarioViewer({
  scenario,
  discreteScenario,
  movementPlan,
  passengerReplay,
  replayMetrics,
  discreteWarning,
  movementPlanWarning,
  passengerReplayWarning,
  replayMetricsWarning,
  artifactSelection,
}: ScenarioViewerProps) {
  const [viewerMode, setViewerMode] = useState<ViewerMode>("scenario");
  const [selected, setSelected] = useState<Selection | null>(null);
  const [hovered, setHovered] = useState<Selection | null>(null);
  const [toggles, setToggles] = useState<ViewerToggles>({
    serviceRoutes: true,
    skipRoutes: true,
    demand: true,
    parameters: true,
  });
  const [discreteMode, setDiscreteMode] = useState<DiscreteOverlayMode>("neighborhood");
  const [discreteToggles, setDiscreteToggles] = useState<DiscreteViewerToggles>({
    enabled: true,
    showMoveArcs: true,
    showWaitArcs: true,
    showOwnSegmentHeadway: true,
    showAdjacentSegmentHeadway: true,
    showMultiSegmentHeadway: true,
  });

  const counts = useMemo(
    () => ({
      stations: scenario.stations.length,
      nodes: scenario.physical_nodes.length,
      segments: scenario.track_segments.length,
      routes: scenario.station_routes.length,
      discreteNodes: discreteScenario?.nodes.length ?? 0,
      constraints: discreteScenario?.constraints.length ?? 0,
    }),
    [scenario, discreteScenario],
  );

  function toggle(key: keyof ViewerToggles) {
    setToggles((current) => ({ ...current, [key]: !current[key] }));
  }

  function toggleDiscrete(key: keyof DiscreteViewerToggles) {
    setDiscreteToggles((current) => ({ ...current, [key]: !current[key] }));
  }

  function handleSelect(selection: Selection | null) {
    setSelected(selection);
    if (selection && (selection.type === "node" || selection.type === "segment" || selection.type === "route")) {
      setDiscreteToggles((current) => ({ ...current, enabled: true }));
    }
  }

  const activeSelection = isDiscreteSelection(hovered) ? hovered : selected;
  const hasDiscrete = discreteScenario !== null;

  return (
    <main className="viewer-shell">
      <ViewerHeader
        scenarioId={scenario.scenario_id}
        counts={counts}
        hasDiscrete={hasDiscrete}
        artifactSelection={artifactSelection}
      />

      <ViewerModeTabs viewerMode={viewerMode} onViewerModeChange={setViewerMode} />

      {viewerMode === "scenario" ? (
        <>
          <ScenarioToolbar toggles={toggles} onToggle={toggle} />
          <DiscreteOverlayToolbar
            hasDiscrete={hasDiscrete}
            selected={selected}
            discreteMode={discreteMode}
            discreteToggles={discreteToggles}
            warning={discreteWarning}
            onDiscreteModeChange={setDiscreteMode}
            onToggle={toggleDiscrete}
            onClearSelection={() => setSelected(null)}
          />
          <ScenarioView
            scenario={scenario}
            discreteScenario={discreteScenario}
            selected={selected}
            hovered={hovered}
            activeSelection={activeSelection}
            toggles={toggles}
            discreteMode={discreteMode}
            discreteToggles={discreteToggles}
            onSelect={handleSelect}
            onHover={setHovered}
          />
        </>
      ) : (
        viewerMode === "graph" ? (
        <GraphSlackView scenario={scenario} discreteScenario={discreteScenario} />
        ) : viewerMode === "metrics" ? (
          <MetricsView
            scenario={scenario}
            replayMetrics={replayMetrics}
            replayMetricsWarning={replayMetricsWarning}
          />
        ) : (
          <ReplayView
            scenario={scenario}
            discreteScenario={discreteScenario}
            movementPlan={movementPlan}
            passengerReplay={passengerReplay}
            movementPlanWarning={movementPlanWarning}
            passengerReplayWarning={passengerReplayWarning}
          />
        )
      )}
    </main>
  );
}

function isDiscreteSelection(selection: Selection | null) {
  return selection?.type === "discrete_node" || selection?.type === "discrete_arc" || selection?.type === "discrete_constraint";
}
