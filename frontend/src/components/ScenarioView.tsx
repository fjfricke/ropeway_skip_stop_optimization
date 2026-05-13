import { Gauge } from "lucide-react";
import { useMemo, useRef } from "react";
import { DemandPanel } from "./DemandPanel";
import { InspectorPanel } from "./InspectorPanel";
import { NetworkSvg } from "./NetworkSvg";
import { ParametersPanel } from "./ParametersPanel";
import { useNetworkPanelContentHeight } from "./useNetworkPanelContentHeight";
import { layoutForScenario } from "../scenarioLayout";
import type { ArcColorMode, DiscreteOverlayMode, DiscreteViewerToggles, ScenarioDisplayMode, ViewerToggles } from "./viewerTypes";
import type { DiscreteScenario, Scenario, Selection } from "../types";

interface ScenarioViewProps {
  scenario: Scenario;
  discreteScenario: DiscreteScenario | null;
  selected: Selection | null;
  hovered: Selection | null;
  activeSelection: Selection | null;
  toggles: ViewerToggles;
  displayMode: ScenarioDisplayMode;
  arcColorMode: ArcColorMode;
  discreteMode: DiscreteOverlayMode;
  discreteToggles: DiscreteViewerToggles;
  onExportClick: () => void;
  onSelect: (selection: Selection | null) => void;
  onHover: (selection: Selection | null) => void;
}

export function ScenarioView({
  scenario,
  discreteScenario,
  selected,
  hovered,
  activeSelection,
  toggles,
  displayMode,
  arcColorMode,
  discreteMode,
  discreteToggles,
  onExportClick,
  onSelect,
  onHover,
}: ScenarioViewProps) {
  const networkPanelRef = useRef<HTMLDivElement | null>(null);
  const sidePanelMaxHeight = useNetworkPanelContentHeight(networkPanelRef);
  const layout = useMemo(() => layoutForScenario(scenario), [scenario]);
  const stationLine = scenario.stations
    .filter((station) => station.kind === "terminal" || station.kind === "service")
    .map((station) => station.id)
    .join("-");

  return (
    <section className="workspace">
      <div className="network-panel" ref={networkPanelRef}>
        <div className="network-panel__header">
          <div>
            <h2>{displayMode === "line" ? "Line View" : "Physical Scenario"}</h2>
            <p>
              {displayMode === "line"
                ? `Schematic ${stationLine} station line`
                : `Circulating ${stationLine} line with terminal turnarounds and skip branches at service stations`}
            </p>
          </div>
          <div className="status-pill">
            <Gauge size={16} />
            validated input
          </div>
        </div>
        <NetworkSvg
          scenario={scenario}
          discreteScenario={discreteScenario}
          layout={layout}
          selected={selected}
          hovered={hovered}
          toggles={toggles}
          displayMode={displayMode}
          arcColorMode={arcColorMode}
          discreteMode={discreteMode}
          discreteToggles={discreteToggles}
          onExportClick={onExportClick}
          onSelect={onSelect}
          onHover={onHover}
        />
      </div>

      <aside className="side-panel" style={sidePanelMaxHeight === null ? undefined : { maxHeight: sidePanelMaxHeight }}>
        <InspectorPanel
          scenario={scenario}
          discreteScenario={discreteScenario}
          selection={activeSelection}
          discreteMode={discreteMode}
          discreteToggles={discreteToggles}
        />
        <ParametersPanel scenario={scenario} />
        <DemandPanel scenario={scenario} />
      </aside>
    </section>
  );
}
