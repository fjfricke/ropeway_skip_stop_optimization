import type {
  EanBuildArtifact,
  EanFleetPlan,
  EanMovementPlan,
  EanPhysicalReplay,
  Scenario,
} from "../types";
import { checkContinuousSpacing } from "./geometry";
import { checkResourceHeadways } from "./headways";
import { validateSafetyInputs } from "./decodeSafetyInputs";
import {
  emptySafetyCounts,
  type ReplaySafetyReport,
} from "./types";

export function certifyReplaySafety({
  scenario,
  artifact,
  movementPlan,
  fleetPlan,
  replay,
}: {
  scenario: Scenario;
  artifact: EanBuildArtifact | null;
  movementPlan: EanMovementPlan | null;
  fleetPlan: EanFleetPlan | null;
  replay: EanPhysicalReplay | null;
}): ReplaySafetyReport {
  const initialDiagnostics = validateTopLevelInputs(
    scenario,
    artifact,
    movementPlan,
    replay,
  );
  if (!artifact || !movementPlan || !replay || !artifact.headway_policy) {
    return {
      status: "indeterminate",
      checkedFromSeconds: 0,
      checkedUntilSeconds: movementPlan?.model_end_seconds ?? replay?.model_end_seconds ?? 0,
      violations: [],
      totalViolationCount: 0,
      minimumHeadwaySlackSeconds: null,
      minimumSpacingSlackM: null,
      diagnostics: unique(initialDiagnostics),
      counts: emptySafetyCounts(),
    };
  }

  initialDiagnostics.push(...validateSafetyInputs({
    scenario,
    artifact,
    movementPlan,
    fleetPlan,
    replay,
  }));

  const headways = checkResourceHeadways({ artifact, movementPlan, fleetPlan, scenario });
  const geometry = checkContinuousSpacing({
    scenario,
    policy: artifact.headway_policy,
    movementPlan,
    replay,
  });
  const diagnostics = unique([
    ...initialDiagnostics,
    ...headways.diagnostics,
    ...geometry.diagnostics,
  ]);
  const violations = [...headways.violations, ...geometry.violations].sort(
    (left, right) => left.timeSeconds - right.timeSeconds || left.id.localeCompare(right.id),
  );
  const totalViolationCount = headways.totalViolationCount + geometry.totalViolationCount;
  const status = totalViolationCount > 0
    ? "unsafe"
    : diagnostics.length > 0
      ? "indeterminate"
      : "safe";
  return {
    status,
    checkedFromSeconds: 0,
    checkedUntilSeconds: movementPlan.model_end_seconds,
    violations,
    totalViolationCount,
    minimumHeadwaySlackSeconds: headways.minimumSlackSeconds,
    minimumSpacingSlackM: geometry.minimumSlackM,
    diagnostics,
    counts: {
      resourceUsages: headways.usageCount,
      resourcePairs: headways.pairCount,
      motionIntervals: geometry.motionIntervalCount,
      geometricPairs: geometry.pairCount,
    },
  };
}

function validateTopLevelInputs(
  scenario: Scenario,
  artifact: EanBuildArtifact | null,
  movementPlan: EanMovementPlan | null,
  replay: EanPhysicalReplay | null,
): string[] {
  const diagnostics: string[] = [];
  if (!artifact) diagnostics.push("EAN build artifact is missing");
  if (!movementPlan) diagnostics.push("EAN movement plan is missing");
  if (!replay) diagnostics.push("EAN physical replay is missing");
  if (artifact && !artifact.headway_policy) diagnostics.push("Complete physical headway policy is missing");
  for (const [label, id] of [
    ["artifact", artifact?.scenario_id],
    ["movement plan", movementPlan?.scenario_id],
    ["physical replay", replay?.scenario_id],
  ] as const) {
    if (id !== undefined && id !== scenario.scenario_id) {
      diagnostics.push(`${label} scenario ${id} does not match ${scenario.scenario_id}`);
    }
  }
  if (
    artifact
    && movementPlan
    && Math.abs(artifact.config.horizon_seconds + artifact.config.tail_seconds - movementPlan.model_end_seconds) > 1e-5
  ) {
    diagnostics.push("Movement-plan horizon does not match the EAN artifact");
  }
  if (movementPlan && replay && Math.abs(movementPlan.model_end_seconds - replay.model_end_seconds) > 1e-5) {
    diagnostics.push("Physical-replay horizon does not match the movement plan");
  }
  return diagnostics;
}

function unique(values: string[]) {
  return [...new Set(values)];
}
