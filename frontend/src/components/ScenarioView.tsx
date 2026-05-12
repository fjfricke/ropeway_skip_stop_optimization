import { Gauge } from "lucide-react";
import { DemandPanel } from "./DemandPanel";
import { InspectorPanel } from "./InspectorPanel";
import { NetworkSvg } from "./NetworkSvg";
import { ParametersPanel } from "./ParametersPanel";
import { threeStationLayout } from "../scenarioLayout";
import type { DiscreteOverlayMode, DiscreteViewerToggles, ViewerToggles } from "./viewerTypes";
import type { DiscreteScenario, Scenario, Selection } from "../types";

interface ScenarioViewProps {
  scenario: Scenario;
  discreteScenario: DiscreteScenario | null;
  selected: Selection | null;
  hovered: Selection | null;
  activeSelection: Selection | null;
  toggles: ViewerToggles;
  discreteMode: DiscreteOverlayMode;
  discreteToggles: DiscreteViewerToggles;
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
  discreteMode,
  discreteToggles,
  onSelect,
  onHover,
}: ScenarioViewProps) {
  return (
    <>
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
            onSelect={onSelect}
            onHover={onHover}
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
  );
}
