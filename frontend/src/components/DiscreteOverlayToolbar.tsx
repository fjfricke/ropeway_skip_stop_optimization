import { CirclePause, Focus, GitMerge, Link2, MoveRight, Network, Radar, Rows3, X } from "lucide-react";
import type { DiscreteOverlayMode, DiscreteViewerToggles } from "./viewerTypes";
import type { Selection } from "../types";

interface DiscreteOverlayToolbarProps {
  hasDiscrete: boolean;
  selected: Selection | null;
  discreteMode: DiscreteOverlayMode;
  discreteToggles: DiscreteViewerToggles;
  warning: string | null;
  onDiscreteModeChange: (mode: DiscreteOverlayMode) => void;
  onToggle: (key: keyof DiscreteViewerToggles) => void;
  onClearSelection: () => void;
}

export function DiscreteOverlayToolbar({
  hasDiscrete,
  selected,
  discreteMode,
  discreteToggles,
  warning,
  onDiscreteModeChange,
  onToggle,
  onClearSelection,
}: DiscreteOverlayToolbarProps) {
  return (
    <section className="toolbar toolbar--discrete" aria-label="Discrete overlay toggles">
      <button
        className={discreteToggles.enabled && hasDiscrete ? "is-active" : ""}
        onClick={() => onToggle("enabled")}
        disabled={!hasDiscrete}
      >
        <Network size={17} />
        Discrete
      </button>
      <button
        className={discreteMode === "selected" ? "is-active" : ""}
        onClick={() => onDiscreteModeChange("selected")}
        disabled={!hasDiscrete || !discreteToggles.enabled}
      >
        <Focus size={17} />
        Selected
      </button>
      <button
        className={discreteMode === "neighborhood" ? "is-active" : ""}
        onClick={() => onDiscreteModeChange("neighborhood")}
        disabled={!hasDiscrete || !discreteToggles.enabled}
      >
        <Radar size={17} />
        Neighborhood
      </button>
      <button
        className={discreteToggles.showMoveArcs ? "is-active" : ""}
        onClick={() => onToggle("showMoveArcs")}
        disabled={!hasDiscrete || !discreteToggles.enabled}
      >
        <MoveRight size={17} />
        Move Arcs
      </button>
      <button
        className={discreteToggles.showWaitArcs ? "is-active" : ""}
        onClick={() => onToggle("showWaitArcs")}
        disabled={!hasDiscrete || !discreteToggles.enabled}
      >
        <CirclePause size={17} />
        Wait Arcs
      </button>
      <button
        className={discreteToggles.showOwnSegmentHeadway ? "is-active" : ""}
        onClick={() => onToggle("showOwnSegmentHeadway")}
        disabled={!hasDiscrete || !discreteToggles.enabled}
      >
        <Rows3 size={17} />
        Own Headway
      </button>
      <button
        className={discreteToggles.showAdjacentSegmentHeadway ? "is-active" : ""}
        onClick={() => onToggle("showAdjacentSegmentHeadway")}
        disabled={!hasDiscrete || !discreteToggles.enabled}
      >
        <Link2 size={17} />
        Adjacent Headway
      </button>
      <button
        className={discreteToggles.showMultiSegmentHeadway ? "is-active" : ""}
        onClick={() => onToggle("showMultiSegmentHeadway")}
        disabled={!hasDiscrete || !discreteToggles.enabled}
      >
        <GitMerge size={17} />
        Multi Headway
      </button>
      <button onClick={onClearSelection} disabled={!selected}>
        <X size={17} />
        Close
      </button>
      {warning ? <span className="toolbar__warning">{warning}</span> : null}
    </section>
  );
}
