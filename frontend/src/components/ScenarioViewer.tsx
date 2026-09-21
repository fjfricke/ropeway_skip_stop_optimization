import { useCallback, useEffect, useMemo, useState } from "react";
import { DiscreteOverlayToolbar } from "./DiscreteOverlayToolbar";
import { EanMetricsView } from "./EanMetricsView";
import { EanProgressView } from "./EanProgressView";
import { EanReplayExportJobHost, type EanReplayVideoExportJob } from "./EanReplayExportJobHost";
import { EanReplayExportModal } from "./EanReplayExportModal";
import { EanReplayView } from "./EanReplayView";
import { EanView } from "./EanView";
import { GraphSlackView } from "./GraphSlackView";
import { MetricsView } from "./MetricsView";
import { ReplayView } from "./ReplayView";
import { ScenarioExportModal } from "./ScenarioExportModal";
import { NetworkContextToggles, ScenarioToolbar } from "./ScenarioToolbar";
import { ScenarioView } from "./ScenarioView";
import { ViewerHeader } from "./ViewerHeader";
import { OptimizationModeTabs, ViewerModeTabs } from "./ViewerModeTabs";
import { layoutForScenario } from "../scenarioLayout";
import type {
  ArtifactSelectionControl,
  ArcColorMode,
  AvailableViewerModes,
  DiscreteOverlayMode,
  DiscreteViewerToggles,
  ScenarioDisplayMode,
  ViewerMode,
  ViewerToggles,
} from "./viewerTypes";
import type {
  DiscreteScenario,
  EanBuildArtifact,
  EanMovementPlan,
  EanPassengerServiceResult,
  EanPhysicalReplay,
  ExportArtifactSetBackend,
  MovementPlan,
  PassengerReplayResult,
  ReplayMetrics,
  Scenario,
  Selection,
} from "../types";
import { useReplaySafetyReport } from "../safety/useReplaySafetyReport";

interface ScenarioViewerProps {
  initialMode?: ViewerMode;
  scenario: Scenario;
  discreteScenario: DiscreteScenario | null;
  movementPlan: MovementPlan | null;
  passengerReplay: PassengerReplayResult | null;
  replayMetrics: ReplayMetrics | null;
  eanInput: EanBuildArtifact | null;
  eanResult: EanMovementPlan | null;
  eanReplay: EanPhysicalReplay | null;
  eanPassengerService: EanPassengerServiceResult | null;
  discreteWarning: string | null;
  movementPlanWarning: string | null;
  passengerReplayWarning: string | null;
  replayMetricsWarning: string | null;
  eanInputWarning: string | null;
  eanResultWarning: string | null;
  eanReplayWarning: string | null;
  eanPassengerServiceWarning: string | null;
  artifactSelection: ArtifactSelectionControl;
}

const DISCRETE_REPLAY_TOGGLES: ViewerToggles = {
  serviceRoutes: true,
  skipRoutes: false,
  demand: true,
  stationZones: true,
  nodeLabels: true,
  arcLabels: false,
};

const EAN_REPLAY_TOGGLES: ViewerToggles = {
  serviceRoutes: true,
  skipRoutes: true,
  demand: true,
  stationZones: true,
  nodeLabels: true,
  arcLabels: false,
};

export function ScenarioViewer({
  initialMode = "scenario",
  scenario,
  discreteScenario,
  movementPlan,
  passengerReplay,
  replayMetrics,
  eanInput,
  eanResult,
  eanReplay,
  eanPassengerService,
  discreteWarning,
  movementPlanWarning,
  passengerReplayWarning,
  replayMetricsWarning,
  eanInputWarning,
  eanResultWarning,
  eanReplayWarning,
  eanPassengerServiceWarning,
  artifactSelection,
}: ScenarioViewerProps) {
  const [viewerMode, setViewerMode] = useState<ViewerMode>(initialMode);
  const [selected, setSelected] = useState<Selection | null>(null);
  const [hovered, setHovered] = useState<Selection | null>(null);
  const [toggles, setToggles] = useState<ViewerToggles>({
    serviceRoutes: true,
    skipRoutes: true,
    demand: true,
    stationZones: true,
    nodeLabels: true,
    arcLabels: false,
  });
  const [scenarioDisplayMode, setScenarioDisplayMode] = useState<ScenarioDisplayMode>("line");
  const [arcColorMode, setArcColorMode] = useState<ArcColorMode>("type");
  const [discreteReplayToggles, setDiscreteReplayToggles] = useState<ViewerToggles>(DISCRETE_REPLAY_TOGGLES);
  const [discreteReplayArcColorMode, setDiscreteReplayArcColorMode] = useState<ArcColorMode>("type");
  const [eanReplayToggles, setEanReplayToggles] = useState<ViewerToggles>(EAN_REPLAY_TOGGLES);
  const [eanReplayArcColorMode, setEanReplayArcColorMode] = useState<ArcColorMode>("type");
  const [discreteMode, setDiscreteMode] = useState<DiscreteOverlayMode>("neighborhood");
  const [isExportOpen, setIsExportOpen] = useState(false);
  const [eanReplayExportTime, setEanReplayExportTime] = useState<number | null>(null);
  const [eanReplayExportJob, setEanReplayExportJob] = useState<EanReplayVideoExportJob | null>(null);
  const [discreteToggles, setDiscreteToggles] = useState<DiscreteViewerToggles>({
    enabled: true,
    showMoveArcs: true,
    showWaitArcs: true,
    showOwnSegmentHeadway: true,
    showAdjacentSegmentHeadway: true,
    showMultiSegmentHeadway: true,
  });

  const selectedBackend = artifactSelection.selectedBackend;
  const safetyMovementPlan = eanPassengerService?.movement_plan ?? eanResult;
  const safetyFleetPlan = safetyMovementPlan?.fleet_plan ?? eanPassengerService?.fleet_plan ?? null;
  const replaySafety = useReplaySafetyReport({
    scenario,
    artifact: eanInput,
    movementPlan: safetyMovementPlan,
    fleetPlan: safetyFleetPlan,
    replay: eanReplay,
  });
  const visibleDiscreteScenario = selectedBackend === "discrete" ? discreteScenario : null;
  const scenarioLayout = useMemo(() => layoutForScenario(scenario), [scenario]);
  const counts = useMemo(
    () => ({
      stations: scenario.stations.length,
      nodes: scenario.physical_nodes.length,
      segments: scenario.track_segments.length,
      routes: scenario.station_routes.length,
      discreteNodes: visibleDiscreteScenario?.nodes.length ?? 0,
      constraints: visibleDiscreteScenario?.constraints.length ?? 0,
    }),
    [scenario, visibleDiscreteScenario],
  );

  function toggle(key: keyof ViewerToggles) {
    setToggles((current) => ({ ...current, [key]: !current[key] }));
  }

  function toggleArcColorMode() {
    setArcColorMode((current) => (current === "type" ? "speed" : "type"));
  }

  function toggleDiscreteReplay(key: keyof ViewerToggles) {
    setDiscreteReplayToggles((current) => ({ ...current, [key]: !current[key] }));
  }

  function toggleDiscreteReplayArcColorMode() {
    setDiscreteReplayArcColorMode((current) => (current === "type" ? "speed" : "type"));
  }

  function toggleEanReplay(key: keyof ViewerToggles) {
    setEanReplayToggles((current) => ({ ...current, [key]: !current[key] }));
  }

  function toggleEanReplayArcColorMode() {
    setEanReplayArcColorMode((current) => (current === "type" ? "speed" : "type"));
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

  const activeSelection = selectedBackend === "discrete" && isDiscreteSelection(hovered) ? hovered : selected;
  const hasDiscrete = visibleDiscreteScenario !== null;
  const availableModes: AvailableViewerModes = useMemo(
    () => ({
      scenario: true,
      graph: visibleDiscreteScenario !== null,
      metrics: selectedBackend === "discrete" && replayMetrics !== null,
      replay: visibleDiscreteScenario !== null && movementPlan !== null,
      ean: selectedBackend === "ean" && (eanInput !== null || eanResult !== null || eanReplay !== null || eanPassengerService !== null),
      ean_progress: selectedBackend === "ean" && (eanPassengerService?.metadata.progress_samples?.length ?? 0) > 0,
      ean_metrics: selectedBackend === "ean" && eanPassengerService?.passenger_plan !== null && eanPassengerService?.passenger_plan !== undefined,
      ean_replay: selectedBackend === "ean" && eanReplay !== null,
    }),
    [eanInput, eanPassengerService, eanReplay, eanResult, movementPlan, replayMetrics, selectedBackend, visibleDiscreteScenario],
  );

  useEffect(() => {
    if (!isViewerModeAvailable(viewerMode, availableModes)) {
      setViewerMode(firstOptimizationMode(selectedBackend, availableModes) ?? "scenario");
    }
  }, [availableModes, selectedBackend, viewerMode]);

  const hasOptimizationModes = firstOptimizationMode(selectedBackend, availableModes) !== null;
  const isReplayMode = viewerMode === "replay" || viewerMode === "ean_replay";

  function handleOptimizationModeChange() {
    const nextMode = firstOptimizationMode(selectedBackend, availableModes);
    if (nextMode) setViewerMode(nextMode);
  }

  const handleDismissEanReplayExportJob = useCallback((jobId: number) => {
    setEanReplayExportJob((current) => (current?.id === jobId ? null : current));
  }, []);

  return (
    <main className="viewer-shell">
      <ViewerHeader
        scenarioId={scenario.scenario_id}
        counts={counts}
        hasDiscrete={hasDiscrete}
        artifactSelection={artifactSelection}
      />

      <ViewerModeTabs
        viewerMode={viewerMode}
        selectedBackend={selectedBackend}
        hasOptimizationModes={hasOptimizationModes}
        onScenarioModeChange={() => setViewerMode("scenario")}
        onOptimizationModeChange={handleOptimizationModeChange}
      />

      {viewerMode === "scenario" ? (
        <>
          <ScenarioToolbar
            toggles={toggles}
            displayMode={scenarioDisplayMode}
            arcColorMode={arcColorMode}
            onToggle={toggle}
            onDisplayModeChange={setScenarioDisplayMode}
            onArcColorModeToggle={toggleArcColorMode}
          />
          {selectedBackend === "discrete" ? (
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
          ) : null}
          <ScenarioView
            scenario={scenario}
            discreteScenario={visibleDiscreteScenario}
            selected={selected}
            hovered={hovered}
            activeSelection={activeSelection}
            toggles={toggles}
            displayMode={scenarioDisplayMode}
            arcColorMode={arcColorMode}
            discreteMode={discreteMode}
            discreteToggles={discreteToggles}
            onExportClick={() => setIsExportOpen(true)}
            onSelect={handleSelect}
            onHover={setHovered}
          />
          {isExportOpen ? (
            <ScenarioExportModal
              scenario={scenario}
              layout={scenarioLayout}
              displayMode={scenarioDisplayMode}
              toggles={toggles}
              arcColorMode={arcColorMode}
              onClose={() => setIsExportOpen(false)}
            />
          ) : null}
        </>
      ) : (
        <>
          <section className="toolbar toolbar--optimization-context" aria-label="Optimization view controls">
            <OptimizationModeTabs
              viewerMode={viewerMode}
              selectedBackend={selectedBackend}
              availableModes={availableModes}
              onViewerModeChange={setViewerMode}
            />
            {isReplayMode ? (
              <>
                <span className="toolbar__spacer" aria-hidden="true" />
                <div className="toolbar__context-toggle" aria-label="Replay network toggles">
                  {viewerMode === "ean_replay" ? (
                    <NetworkContextToggles
                      toggles={eanReplayToggles}
                      arcColorMode={eanReplayArcColorMode}
                      showDemandToggle
                      onToggle={toggleEanReplay}
                      onArcColorModeToggle={toggleEanReplayArcColorMode}
                    />
                  ) : (
                    <NetworkContextToggles
                      toggles={discreteReplayToggles}
                      arcColorMode={discreteReplayArcColorMode}
                      showDemandToggle
                      onToggle={toggleDiscreteReplay}
                      onArcColorModeToggle={toggleDiscreteReplayArcColorMode}
                    />
                  )}
                </div>
              </>
            ) : null}
          </section>
          {viewerMode === "graph" ? (
            <GraphSlackView
              scenario={scenario}
              discreteScenario={discreteScenario}
              eanPassengerService={eanPassengerService}
            />
          ) : viewerMode === "metrics" ? (
            <MetricsView
              scenario={scenario}
              replayMetrics={replayMetrics}
              replayMetricsWarning={replayMetricsWarning}
            />
          ) : viewerMode === "ean" ? (
            <EanView
              scenario={scenario}
              eanInput={eanInput}
              eanResult={eanResult}
              eanReplay={eanReplay}
              eanPassengerService={eanPassengerService}
              eanInputWarning={eanInputWarning}
              eanResultWarning={eanResultWarning}
              eanReplayWarning={eanReplayWarning}
              eanPassengerServiceWarning={eanPassengerServiceWarning}
            />
          ) : viewerMode === "ean_progress" ? (
            <EanProgressView
              eanPassengerService={eanPassengerService}
              eanPassengerServiceWarning={eanPassengerServiceWarning}
            />
          ) : viewerMode === "ean_metrics" ? (
            <EanMetricsView
              scenario={scenario}
              eanPassengerService={eanPassengerService}
              eanPassengerServiceWarning={eanPassengerServiceWarning}
            />
          ) : viewerMode === "ean_replay" ? (
            <>
              <EanReplayView
                scenario={scenario}
                headwayPolicy={eanInput?.headway_policy ?? null}
                eanReplay={eanReplay}
                eanPassengerService={eanPassengerService}
                eanReplayWarning={eanReplayWarning}
                eanPassengerServiceWarning={eanPassengerServiceWarning}
                safetyReport={replaySafety.report}
                safetyError={replaySafety.error}
                safetyChecking={replaySafety.isChecking}
                toggles={eanReplayToggles}
                arcColorMode={eanReplayArcColorMode}
                onExportClick={(timeSeconds) => setEanReplayExportTime(timeSeconds)}
              />
              {eanReplayExportTime !== null && eanReplay ? (
                <EanReplayExportModal
                  scenario={scenario}
                  layout={scenarioLayout}
                  eanReplay={eanReplay}
                  eanPassengerService={eanPassengerService}
                  safetyReport={replaySafety.report}
                  toggles={eanReplayToggles}
                  arcColorMode={eanReplayArcColorMode}
                  initialTimeSeconds={eanReplayExportTime}
                  isVideoExportRunning={eanReplayExportJob !== null}
                  onStartVideoExport={(config, format) => {
                    if (eanReplayExportJob !== null) return;
                    setEanReplayExportJob({
                      id: Date.now(),
                      scenario,
                      layout: scenarioLayout,
                      eanReplay,
                      eanPassengerService,
                      safetyReport: replaySafety.report,
                      config,
                      format,
                    });
                  }}
                  onClose={() => setEanReplayExportTime(null)}
                />
              ) : null}
            </>
          ) : (
            <ReplayView
              scenario={scenario}
              discreteScenario={discreteScenario}
              movementPlan={movementPlan}
              passengerReplay={passengerReplay}
              movementPlanWarning={movementPlanWarning}
              passengerReplayWarning={passengerReplayWarning}
              toggles={discreteReplayToggles}
              arcColorMode={discreteReplayArcColorMode}
            />
          )}
        </>
      )}
      <EanReplayExportJobHost
        job={eanReplayExportJob}
        onDismiss={handleDismissEanReplayExportJob}
      />
    </main>
  );
}

function isDiscreteSelection(selection: Selection | null) {
  return selection?.type === "discrete_node" || selection?.type === "discrete_arc" || selection?.type === "discrete_constraint";
}

function isViewerModeAvailable(mode: ViewerMode, availableModes: AvailableViewerModes) {
  return availableModes[mode];
}

function firstOptimizationMode(selectedBackend: ExportArtifactSetBackend, availableModes: AvailableViewerModes): ViewerMode | null {
  if (selectedBackend === "ean") {
    if (availableModes.ean) return "ean";
    if (availableModes.ean_progress) return "ean_progress";
    if (availableModes.ean_metrics) return "ean_metrics";
    if (availableModes.ean_replay) return "ean_replay";
    return null;
  }

  if (selectedBackend === "discrete") {
    if (availableModes.graph) return "graph";
    if (availableModes.metrics) return "metrics";
    if (availableModes.replay) return "replay";
  }

  return null;
}
