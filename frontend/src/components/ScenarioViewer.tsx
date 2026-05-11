import {
  BarChart3,
  CirclePause,
  Focus,
  Gauge,
  GitBranch,
  GitMerge,
  Link2,
  MoveRight,
  Network,
  PlayCircle,
  Radar,
  Route,
  Rows3,
  SlidersHorizontal,
  Users,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";
import { DemandPanel } from "./DemandPanel";
import { GraphSlackView } from "./GraphSlackView";
import { InspectorPanel } from "./InspectorPanel";
import { NetworkSvg } from "./NetworkSvg";
import { ParametersPanel } from "./ParametersPanel";
import { ReplayView } from "./ReplayView";
import { threeStationLayout } from "../scenarioLayout";
import type { DiscreteScenario, MovementPlan, PassengerReplayResult, Scenario, Selection } from "../types";

interface ScenarioViewerProps {
  scenario: Scenario;
  discreteScenario: DiscreteScenario | null;
  movementPlan: MovementPlan | null;
  passengerReplay: PassengerReplayResult | null;
  discreteWarning: string | null;
  movementPlanWarning: string | null;
  passengerReplayWarning: string | null;
}

export interface ViewerToggles {
  serviceRoutes: boolean;
  skipRoutes: boolean;
  demand: boolean;
  parameters: boolean;
}

export type DiscreteOverlayMode = "selected" | "neighborhood";
type ViewerMode = "scenario" | "graph" | "replay";

export interface DiscreteViewerToggles {
  enabled: boolean;
  showMoveArcs: boolean;
  showWaitArcs: boolean;
  showOwnSegmentHeadway: boolean;
  showAdjacentSegmentHeadway: boolean;
  showMultiSegmentHeadway: boolean;
}

export function ScenarioViewer({
  scenario,
  discreteScenario,
  movementPlan,
  passengerReplay,
  discreteWarning,
  movementPlanWarning,
  passengerReplayWarning,
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
      <header className="topbar">
        <div>
          <p className="eyebrow">Ropeway Scenario Viewer</p>
          <h1>{scenario.scenario_id}</h1>
        </div>
        <div className="topbar__meta" aria-label="Scenario counts">
          <span>{counts.stations} stations</span>
          <span>{counts.nodes} nodes</span>
          <span>{counts.segments} segments</span>
          <span>{counts.routes} routes</span>
          {hasDiscrete ? <span>{counts.discreteNodes} discrete nodes</span> : null}
          {hasDiscrete ? <span>{counts.constraints} constraints</span> : null}
        </div>
      </header>

      <section className="toolbar toolbar--mode" aria-label="Viewer mode">
        <button className={viewerMode === "scenario" ? "is-active" : ""} onClick={() => setViewerMode("scenario")}>
          <Network size={17} />
          Scenario View
        </button>
        <button className={viewerMode === "graph" ? "is-active" : ""} onClick={() => setViewerMode("graph")}>
          <BarChart3 size={17} />
          Graph View
        </button>
        <button className={viewerMode === "replay" ? "is-active" : ""} onClick={() => setViewerMode("replay")}>
          <PlayCircle size={17} />
          Replay View
        </button>
      </section>

      {viewerMode === "scenario" ? (
        <>
          <section className="toolbar" aria-label="Scenario view toggles">
        <button className={toggles.serviceRoutes ? "is-active" : ""} onClick={() => toggle("serviceRoutes")}>
          <Route size={17} />
          Service
        </button>
        <button className={toggles.skipRoutes ? "is-active" : ""} onClick={() => toggle("skipRoutes")}>
          <GitBranch size={17} />
          Skip
        </button>
        <button className={toggles.demand ? "is-active" : ""} onClick={() => toggle("demand")}>
          <Users size={17} />
          Demand
        </button>
        <button className={toggles.parameters ? "is-active" : ""} onClick={() => toggle("parameters")}>
          <SlidersHorizontal size={17} />
          Parameters
        </button>
          </section>

          <section className="toolbar toolbar--discrete" aria-label="Discrete overlay toggles">
        <button
          className={discreteToggles.enabled && hasDiscrete ? "is-active" : ""}
          onClick={() => toggleDiscrete("enabled")}
          disabled={!hasDiscrete}
        >
          <Network size={17} />
          Discrete
        </button>
        <button
          className={discreteMode === "selected" ? "is-active" : ""}
          onClick={() => setDiscreteMode("selected")}
          disabled={!hasDiscrete || !discreteToggles.enabled}
        >
          <Focus size={17} />
          Selected
        </button>
        <button
          className={discreteMode === "neighborhood" ? "is-active" : ""}
          onClick={() => setDiscreteMode("neighborhood")}
          disabled={!hasDiscrete || !discreteToggles.enabled}
        >
          <Radar size={17} />
          Neighborhood
        </button>
        <button
          className={discreteToggles.showMoveArcs ? "is-active" : ""}
          onClick={() => toggleDiscrete("showMoveArcs")}
          disabled={!hasDiscrete || !discreteToggles.enabled}
        >
          <MoveRight size={17} />
          Move Arcs
        </button>
        <button
          className={discreteToggles.showWaitArcs ? "is-active" : ""}
          onClick={() => toggleDiscrete("showWaitArcs")}
          disabled={!hasDiscrete || !discreteToggles.enabled}
        >
          <CirclePause size={17} />
          Wait Arcs
        </button>
        <button
          className={discreteToggles.showOwnSegmentHeadway ? "is-active" : ""}
          onClick={() => toggleDiscrete("showOwnSegmentHeadway")}
          disabled={!hasDiscrete || !discreteToggles.enabled}
        >
          <Rows3 size={17} />
          Own Headway
        </button>
        <button
          className={discreteToggles.showAdjacentSegmentHeadway ? "is-active" : ""}
          onClick={() => toggleDiscrete("showAdjacentSegmentHeadway")}
          disabled={!hasDiscrete || !discreteToggles.enabled}
        >
          <Link2 size={17} />
          Adjacent Headway
        </button>
        <button
          className={discreteToggles.showMultiSegmentHeadway ? "is-active" : ""}
          onClick={() => toggleDiscrete("showMultiSegmentHeadway")}
          disabled={!hasDiscrete || !discreteToggles.enabled}
        >
          <GitMerge size={17} />
          Multi Headway
        </button>
        <button onClick={() => setSelected(null)} disabled={!selected}>
          <X size={17} />
          Close
        </button>
        {discreteWarning ? <span className="toolbar__warning">{discreteWarning}</span> : null}
          </section>

          <section className="workspace">
        <div className="network-panel">
          <div className="network-panel__header">
            <div>
              <h2>Physical Scenario</h2>
              <p>Circulating L-M-R line with terminal turnarounds and skip branches at M</p>
            </div>
            <div className="status-pill">
              <Gauge size={16} />
              validated input
            </div>
          </div>
          <NetworkSvg
            scenario={scenario}
            discreteScenario={discreteScenario}
            layout={threeStationLayout}
            selected={selected}
            hovered={hovered}
            toggles={toggles}
            discreteMode={discreteMode}
            discreteToggles={discreteToggles}
            onSelect={handleSelect}
            onHover={setHovered}
          />
        </div>

        <aside className="side-panel">
          <InspectorPanel
            scenario={scenario}
            discreteScenario={discreteScenario}
            selection={activeSelection}
            discreteMode={discreteMode}
            discreteToggles={discreteToggles}
          />
          {toggles.parameters ? <ParametersPanel scenario={scenario} /> : null}
          {toggles.demand ? <DemandPanel scenario={scenario} /> : null}
        </aside>
          </section>

          <section className="timeline-reserve">
        <span>Replay layer</span>
        <div className="timeline-reserve__track" />
        <span>planned</span>
          </section>
        </>
      ) : (
        viewerMode === "graph" ? (
        <GraphSlackView scenario={scenario} discreteScenario={discreteScenario} />
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
