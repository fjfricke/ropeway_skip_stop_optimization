import type {
  EanBuildArtifact,
  EanFleetPlan,
  EanMovementPlan,
  EanPhysicalReplay,
  Scenario,
} from "../types";

/** Runtime validation for JSON that TypeScript's static types cannot protect. */
export function validateSafetyInputs({
  scenario,
  artifact,
  movementPlan,
  fleetPlan,
  replay,
}: {
  scenario: Scenario;
  artifact: EanBuildArtifact;
  movementPlan: EanMovementPlan;
  fleetPlan: EanFleetPlan | null;
  replay: EanPhysicalReplay;
}): string[] {
  const diagnostics: string[] = [];
  if (artifact.safety_schema_version !== "frontend_replay_safety_v1") {
    diagnostics.push("Unsupported or missing frontend safety schema version");
  }
  if (!Array.isArray(scenario.physical_nodes) || !Array.isArray(scenario.track_segments)) {
    return ["Physical scenario topology is malformed"];
  }
  const nodeIds = uniqueIds(scenario.physical_nodes, "physical node", diagnostics);
  const segmentIds = uniqueIds(scenario.track_segments, "track segment", diagnostics);
  const replaySegmentIds = new Set(
    (replay.events ?? []).flatMap((event) => event.source_segment_ids ?? []),
  );
  for (const segment of scenario.track_segments) {
    if (!nodeIds.has(segment.from_node_id) || !nodeIds.has(segment.to_node_id)) {
      diagnostics.push(`Segment ${segment.id} references a missing physical node`);
    }
    if (!positiveFinite(segment.length_m)) diagnostics.push(`Segment ${segment.id} has invalid length`);
    if (!replaySegmentIds.has(segment.id)) continue;
    const profile = segment.speed_profile;
    if (!profile) {
      diagnostics.push(`Segment ${segment.id} has no speed profile`);
    } else if (profile.kind === "constant") {
      if (!positiveFinite(profile.speed_m_per_s)) diagnostics.push(`Segment ${segment.id} has invalid constant speed`);
    } else if (profile.kind === "linear") {
      if (!nonnegativeFinite(profile.start_speed_m_per_s) || !nonnegativeFinite(profile.end_speed_m_per_s)) {
        diagnostics.push(`Segment ${segment.id} has invalid linear speed`);
      }
      if ((profile.start_speed_m_per_s ?? 0) + (profile.end_speed_m_per_s ?? 0) <= 0) {
        diagnostics.push(`Segment ${segment.id} has zero average speed`);
      }
    } else {
      diagnostics.push(`Segment ${segment.id} has unsupported speed profile`);
    }
  }

  if (!positiveFinite(movementPlan.model_end_seconds) || !positiveFinite(replay.model_end_seconds)) {
    diagnostics.push("Movement or replay horizon is invalid");
  }
  const trajectoryCabins = new Set<number>();
  for (const trajectory of movementPlan.trajectories ?? []) {
    if (trajectoryCabins.has(trajectory.cabin_id)) diagnostics.push(`Duplicate trajectory for cabin ${trajectory.cabin_id}`);
    trajectoryCabins.add(trajectory.cabin_id);
    const visitIds = new Set<number>();
    for (const visit of trajectory.visits ?? []) {
      if (visit.cabin_id !== trajectory.cabin_id) diagnostics.push(`Visit cabin mismatch for cabin ${trajectory.cabin_id}`);
      if (visitIds.has(visit.visit_index)) diagnostics.push(`Duplicate visit ${visit.visit_index} for cabin ${trajectory.cabin_id}`);
      visitIds.add(visit.visit_index);
      for (const value of [visit.switch_time_seconds, visit.exit_switch_time_seconds, visit.next_switch_time_seconds, visit.wait_seconds]) {
        if (!Number.isFinite(value)) diagnostics.push(`Visit ${visit.visit_index} for cabin ${trajectory.cabin_id} has non-finite times`);
      }
    }
  }
  for (const event of replay.events ?? []) {
    if (!Number.isFinite(event.time_seconds)) diagnostics.push(`Replay event for cabin ${event.cabin_id} has non-finite time`);
    if (!nodeIds.has(event.physical_node_id)) diagnostics.push(`Replay event references missing node ${event.physical_node_id}`);
    for (const segmentId of event.source_segment_ids ?? []) {
      if (!segmentIds.has(segmentId)) diagnostics.push(`Replay event references missing segment ${segmentId}`);
    }
  }

  const policy = artifact.headway_policy;
  if (!policy || !Array.isArray(policy.rules) || !Array.isArray(policy.resource_requirements)) {
    diagnostics.push("Complete physical headway policy is malformed");
  } else {
    const ruleIds = uniqueIds(policy.rules, "headway rule", diagnostics);
    for (const rule of policy.rules) {
      const values = rule.kind === "constant"
        ? [rule.seconds]
        : rule.kind === "leader_behavior"
          ? [rule.bypass_leader_seconds, rule.service_leader_seconds]
          : [];
      if (values.length === 0 || values.some((value) => !positiveFinite(value))) {
        diagnostics.push(`Headway rule ${rule.id} is invalid or unsupported`);
      }
    }
    uniqueIds(policy.resource_requirements, "headway resource", diagnostics);
    for (const resource of policy.resource_requirements) {
      if (!ruleIds.has(resource.rule_id)) diagnostics.push(`Headway resource ${resource.id} references missing rule ${resource.rule_id}`);
      if (!nodeIds.has(resource.exit_switch_id)) diagnostics.push(`Headway resource ${resource.id} references missing exit switch ${resource.exit_switch_id}`);
    }
  }

  if ((artifact.fleet_mode ?? "fixed_starts") === "optimized_initial_placement") {
    if (!fleetPlan) diagnostics.push("OIP artifact has no matching fleet plan");
    if (fleetPlan?.mode !== "optimized_initial_placement") diagnostics.push("OIP fleet plan has an incompatible mode");
  }
  return unique(diagnostics);
}

function uniqueIds<T extends { id: string }>(values: T[], label: string, diagnostics: string[]): Set<string> {
  const result = new Set<string>();
  for (const value of values) {
    if (typeof value.id !== "string" || value.id.length === 0 || result.has(value.id)) {
      diagnostics.push(`Duplicate or empty ${label} ID ${String(value.id)}`);
    }
    result.add(value.id);
  }
  return result;
}

function positiveFinite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function nonnegativeFinite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function unique(values: string[]) {
  return [...new Set(values)];
}
