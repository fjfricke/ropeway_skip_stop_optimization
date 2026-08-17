import type { HeadwayRouteBehavior } from "../types";

export type ReplaySafetyStatus = "safe" | "unsafe" | "indeterminate";
export type ReplaySafetyViolationKind = "resource_headway" | "initial_boundary" | "geometric_spacing";

export interface ReplaySafetyViolation {
  id: string;
  kind: ReplaySafetyViolationKind;
  cabinIds: [number, number];
  visitIndices: [number, number] | null;
  timeSeconds: number;
  activeFromSeconds: number;
  activeUntilSeconds: number;
  resourceId: string | null;
  ruleId: string | null;
  nodeId: string | null;
  segmentId: string | null;
  leaderBehavior: HeadwayRouteBehavior | null;
  actualSeparation: number;
  requiredSeparation: number;
  unit: "s" | "m";
  message: string;
}

export interface ReplaySafetyCounts {
  resourceUsages: number;
  resourcePairs: number;
  motionIntervals: number;
  geometricPairs: number;
}

export interface ReplaySafetyReport {
  status: ReplaySafetyStatus;
  checkedFromSeconds: number;
  checkedUntilSeconds: number;
  violations: ReplaySafetyViolation[];
  totalViolationCount: number;
  minimumHeadwaySlackSeconds: number | null;
  minimumSpacingSlackM: number | null;
  diagnostics: string[];
  counts: ReplaySafetyCounts;
}

export const SAFETY_TOLERANCE_SECONDS = 1e-5;
export const SAFETY_TOLERANCE_M = 1e-6;
export const SAFETY_MARKER_WINDOW_SECONDS = 0.35;
export const MAX_STORED_SAFETY_VIOLATIONS = 1_000;

export function emptySafetyCounts(): ReplaySafetyCounts {
  return {
    resourceUsages: 0,
    resourcePairs: 0,
    motionIntervals: 0,
    geometricPairs: 0,
  };
}

export function safetyViolationsAtTime(
  report: ReplaySafetyReport,
  timeSeconds: number,
): ReplaySafetyViolation[] {
  return report.violations.filter(
    (violation) => (
      timeSeconds >= violation.activeFromSeconds - SAFETY_TOLERANCE_SECONDS
      && timeSeconds <= violation.activeUntilSeconds + SAFETY_TOLERANCE_SECONDS
    ),
  );
}
