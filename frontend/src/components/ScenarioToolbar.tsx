import { GitBranch, Map, Network, Palette, Route, Tags, Users, WholeWord, MapPinned } from "lucide-react";
import type { ArcColorMode, ScenarioDisplayMode, ViewerToggles } from "./viewerTypes";

interface ScenarioToolbarProps {
  toggles: ViewerToggles;
  displayMode: ScenarioDisplayMode;
  arcColorMode: ArcColorMode;
  onToggle: (key: keyof ViewerToggles) => void;
  onDisplayModeChange: (mode: ScenarioDisplayMode) => void;
  onArcColorModeToggle: () => void;
}

export function ScenarioToolbar({
  toggles,
  displayMode,
  arcColorMode,
  onToggle,
  onDisplayModeChange,
  onArcColorModeToggle,
}: ScenarioToolbarProps) {
  return (
    <section className="toolbar" aria-label="Scenario view toggles">
      <div className="toolbar__view-toggle" aria-label="Scenario display mode">
        <button className={displayMode === "line" ? "is-active" : ""} onClick={() => onDisplayModeChange("line")}>
          <Map size={17} />
          Line View
        </button>
        <button className={displayMode === "physical" ? "is-active" : ""} onClick={() => onDisplayModeChange("physical")}>
          <Network size={17} />
          Physical View
        </button>
      </div>
      <span className="toolbar__spacer" aria-hidden="true" />
      <div className="toolbar__context-toggle" aria-label={`${displayMode === "physical" ? "Physical" : "Line"} view toggles`}>
        {displayMode === "physical" ? (
          <NetworkContextToggles toggles={toggles} arcColorMode={arcColorMode} onToggle={onToggle} onArcColorModeToggle={onArcColorModeToggle} />
        ) : (
          <>
            <button className={toggles.nodeLabels ? "is-active" : ""} onClick={() => onToggle("nodeLabels")}>
              <WholeWord size={17} />
              Node Labels
            </button>
            <button className={toggles.demand ? "is-active" : ""} onClick={() => onToggle("demand")}>
              <Users size={17} />
              Demand
            </button>
          </>
        )}
      </div>
    </section>
  );
}

export function NetworkContextToolbar({
  toggles,
  arcColorMode,
  onToggle,
  onArcColorModeToggle,
  showDemandToggle = false,
}: {
  toggles: ViewerToggles;
  arcColorMode: ArcColorMode;
  onToggle: (key: keyof ViewerToggles) => void;
  onArcColorModeToggle: () => void;
  showDemandToggle?: boolean;
}) {
  return (
    <section className="toolbar toolbar--network-context" aria-label="Network view toggles">
      <div className="toolbar__context-toggle" aria-label="Physical view toggles">
        <NetworkContextToggles
          toggles={toggles}
          arcColorMode={arcColorMode}
          showDemandToggle={showDemandToggle}
          onToggle={onToggle}
          onArcColorModeToggle={onArcColorModeToggle}
        />
      </div>
    </section>
  );
}

export function NetworkContextToggles({
  toggles,
  arcColorMode,
  showDemandToggle = false,
  onToggle,
  onArcColorModeToggle,
}: {
  toggles: ViewerToggles;
  arcColorMode: ArcColorMode;
  showDemandToggle?: boolean;
  onToggle: (key: keyof ViewerToggles) => void;
  onArcColorModeToggle: () => void;
}) {
  return (
    <>
      <button className={toggles.serviceRoutes ? "is-active" : ""} onClick={() => onToggle("serviceRoutes")}>
        <Route size={17} />
        Service
      </button>
      <button className={toggles.skipRoutes ? "is-active" : ""} onClick={() => onToggle("skipRoutes")}>
        <GitBranch size={17} />
        Skip
      </button>
      {showDemandToggle ? (
        <button className={toggles.demand ? "is-active" : ""} onClick={() => onToggle("demand")}>
          <Users size={17} />
          Demand
        </button>
      ) : null}
      <button className={toggles.stationZones ? "is-active" : ""} onClick={() => onToggle("stationZones")}>
        <MapPinned size={17} />
        Station Zones
      </button>
      <button className={toggles.nodeLabels ? "is-active" : ""} onClick={() => onToggle("nodeLabels")}>
        <WholeWord size={17} />
        Node Labels
      </button>
      <button className={toggles.arcLabels ? "is-active" : ""} onClick={() => onToggle("arcLabels")}>
        <Tags size={17} />
        Arc Labels
      </button>
      <button className={`is-active toolbar__arc-color-button toolbar__arc-color-button--${arcColorMode}`} onClick={onArcColorModeToggle}>
        <Palette size={17} />
        Arc Color: {arcColorMode === "type" ? "Type" : "Speed"}
      </button>
    </>
  );
}
