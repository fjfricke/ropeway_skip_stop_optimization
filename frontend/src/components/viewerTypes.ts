import type { ExportArtifactSetBackend, ExportScenarioFamilyManifest } from "../types";

export interface ArtifactSelectionControl {
  families: ExportScenarioFamilyManifest[];
  selectedFamilyId: string;
  selectedVariantId: string;
  selectedBackend: ExportArtifactSetBackend;
  selectedArtifactSetId: string;
  isLoading: boolean;
  onFamilyChange: (familyId: string) => void;
  onVariantChange: (variantId: string) => void;
  onBackendChange: (backend: ExportArtifactSetBackend) => void;
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
  nodeLabels: boolean;
  arcLabels: boolean;
}

export type ScenarioExportScope = "all" | "custom";
export type ScenarioExportBasis = "a4_width" | "a4_height";
export type ReplayExportMode = "video" | "frames";
export type DiscreteOverlayMode = "selected" | "neighborhood";
export type ScenarioDisplayMode = "physical" | "line";
export type ArcColorMode = "type" | "speed";
export type ViewerMode = "scenario" | "graph" | "metrics" | "replay" | "ean" | "ean_metrics" | "ean_replay";

export interface ScenarioExportConfig {
  displayMode: ScenarioDisplayMode;
  scope: ScenarioExportScope;
  selectedNodeIds: string[];
  selectedArcIds: string[];
  toggles: ViewerToggles;
  arcColorMode: ArcColorMode;
  basis: ScenarioExportBasis;
  percentage: number;
}

export interface ReplayExportConfig extends ScenarioExportConfig {
  exportMode: ReplayExportMode;
  videoStartSeconds: number;
  videoEndSeconds: number;
  fps: number;
  exportSpeed: number;
  selectedFrameTimes: number[];
  showCabinFill: boolean;
}

export interface AvailableViewerModes {
  scenario: true;
  graph: boolean;
  metrics: boolean;
  replay: boolean;
  ean: boolean;
  ean_metrics: boolean;
  ean_replay: boolean;
}

export interface DiscreteViewerToggles {
  enabled: boolean;
  showMoveArcs: boolean;
  showWaitArcs: boolean;
  showOwnSegmentHeadway: boolean;
  showAdjacentSegmentHeadway: boolean;
  showMultiSegmentHeadway: boolean;
}
