import type { ArcColorMode, ScenarioDisplayMode, ViewerToggles } from "../viewerTypes";

export type ScenarioExportBasis = "a4_width" | "a4_height" | "text_width";
export type ReplayExportMode = "video" | "frames";
export type ReplayVideoExportFormat = "webm" | "mp4";

export interface ScenarioExportConfig {
  displayMode: ScenarioDisplayMode;
  selectedNodeIds: string[];
  selectedArcIds: string[];
  toggles: ViewerToggles;
  stationNames: boolean;
  arcColorMode: ArcColorMode;
  basis: ScenarioExportBasis;
  percentage: number;
}

export interface ReplayExportConfig extends ScenarioExportConfig {
  exportMode: ReplayExportMode;
  videoResolutionHeight: number;
  videoStartSeconds: number;
  videoEndSeconds: number;
  videoFps: number;
  exportSpeed: number;
  selectedFrameTimes: number[];
  showCabinFill: boolean;
}
