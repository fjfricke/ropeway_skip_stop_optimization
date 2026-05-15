import { A4_PORTRAIT_300_DPI } from "../scenarioFigureMetrics";
import type { PlaybackDirection } from "../EanReplayView";
import type { ReplayExportConfig } from "../export/exportTypes";

export const VIDEO_EXPORT_FPS_OPTIONS = [15, 30] as const;
export const DEFAULT_VIDEO_EXPORT_FPS = 15;
export const VIDEO_RESOLUTION_PRESETS = [720, 1080, 1440, 2160] as const;
export const DEFAULT_VIDEO_RESOLUTION_HEIGHT = 1080;

export function exportRenderConfig(config: ReplayExportConfig): ReplayExportConfig {
  if (config.exportMode !== "video") return config;
  return {
    ...config,
    basis: "a4_height",
    percentage: (config.videoResolutionHeight / A4_PORTRAIT_300_DPI.height) * 100,
  };
}

export function normalizeRange(left: number, right: number) {
  return {
    start: Math.min(left, right),
    end: Math.max(left, right),
  };
}

export function roundFrameTime(timeSeconds: number) {
  return Math.round(timeSeconds * 10) / 10;
}

export function replayStartTimeForDirection(timeSeconds: number, direction: PlaybackDirection, min: number, max: number) {
  if (direction === 1 && timeSeconds >= max) return min;
  if (direction === -1 && timeSeconds <= min) return max;
  return timeSeconds;
}
