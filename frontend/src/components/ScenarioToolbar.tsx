import { GitBranch, Route, SlidersHorizontal, Users } from "lucide-react";
import type { ViewerToggles } from "./viewerTypes";

interface ScenarioToolbarProps {
  toggles: ViewerToggles;
  onToggle: (key: keyof ViewerToggles) => void;
}

export function ScenarioToolbar({ toggles, onToggle }: ScenarioToolbarProps) {
  return (
    <section className="toolbar" aria-label="Scenario view toggles">
      <button className={toggles.serviceRoutes ? "is-active" : ""} onClick={() => onToggle("serviceRoutes")}>
        <Route size={17} />
        Service
      </button>
      <button className={toggles.skipRoutes ? "is-active" : ""} onClick={() => onToggle("skipRoutes")}>
        <GitBranch size={17} />
        Skip
      </button>
      <button className={toggles.demand ? "is-active" : ""} onClick={() => onToggle("demand")}>
        <Users size={17} />
        Demand
      </button>
      <button className={toggles.parameters ? "is-active" : ""} onClick={() => onToggle("parameters")}>
        <SlidersHorizontal size={17} />
        Parameters
      </button>
    </section>
  );
}
