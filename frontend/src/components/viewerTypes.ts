import type { ExportExampleManifest } from "../types";

export interface ArtifactSelectionControl {
  examples: ExportExampleManifest[];
  selectedExampleId: string;
  selectedArtifactSetId: string;
  isLoading: boolean;
  onExampleChange: (exampleId: string) => void;
  onArtifactSetChange: (artifactSetId: string) => void;
}

export interface ViewerCounts {
  stations: number;
  nodes: number;
  segments: number;
  routes: number;
  discreteNodes: number;
  constraints: number;
}

export interface ViewerToggles {
  serviceRoutes: boolean;
  skipRoutes: boolean;
  demand: boolean;
  parameters: boolean;
}

export type DiscreteOverlayMode = "selected" | "neighborhood";
export type ViewerMode = "scenario" | "graph" | "metrics" | "replay";

export interface DiscreteViewerToggles {
  enabled: boolean;
  showMoveArcs: boolean;
  showWaitArcs: boolean;
  showOwnSegmentHeadway: boolean;
  showAdjacentSegmentHeadway: boolean;
  showMultiSegmentHeadway: boolean;
}
