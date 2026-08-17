import { useEffect, useState } from "react";
import type {
  EanBuildArtifact,
  EanFleetPlan,
  EanMovementPlan,
  EanPhysicalReplay,
  Scenario,
} from "../types";
import type { ReplaySafetyReport } from "./types";

export function useReplaySafetyReport({
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
}) {
  const [report, setReport] = useState<ReplaySafetyReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setReport(null);
    setError(null);
    const worker = new Worker(
      new URL("./replaySafety.worker.ts", import.meta.url),
      { type: "module" },
    );
    worker.onmessage = (event: MessageEvent<{ report?: ReplaySafetyReport; error?: string }>) => {
      if (event.data.report) setReport(event.data.report);
      if (event.data.error) setError(event.data.error);
    };
    worker.onerror = (event) => setError(event.message || "Frontend safety worker failed");
    worker.postMessage({
      scenario,
      artifact: artifact ? compactArtifactForSafety(artifact) : null,
      movementPlan,
      fleetPlan,
      replay,
    });
    return () => worker.terminate();
  }, [artifact, fleetPlan, movementPlan, replay, scenario]);

  return { report, error, isChecking: report === null && error === null };
}

/** Excludes eager candidate/pair materialization from the worker clone. */
export function compactArtifactForSafety(artifact: EanBuildArtifact): EanBuildArtifact {
  return {
    scenario_id: artifact.scenario_id,
    config: artifact.config,
    switch_cycle: [],
    timings: [],
    cabin_starts: [],
    switch_visits: [],
    switch_transitions: [],
    headway_checkpoints: [],
    headway_candidates: [],
    headway_pairs: [],
    headway_pair_scope: artifact.headway_pair_scope,
    fleet_mode: artifact.fleet_mode,
    headway_policy: artifact.headway_policy,
    effective_headway_policy: artifact.effective_headway_policy,
    safety_schema_version: artifact.safety_schema_version,
  };
}
