import type {
  DerivedHeadwayPolicy,
  DerivedHeadwayResource,
  EanBuildArtifact,
  EanFleetPlan,
  EanMovementPlan,
  EanVisitPlan,
  HeadwayRouteBehavior,
  HeadwayRule,
  Scenario,
} from "../types";
import {
  MAX_STORED_SAFETY_VIOLATIONS,
  SAFETY_MARKER_WINDOW_SECONDS,
  SAFETY_TOLERANCE_SECONDS,
  type ReplaySafetyViolation,
} from "./types";

export interface ResourceHeadwayCheckResult {
  violations: ReplaySafetyViolation[];
  totalViolationCount: number;
  minimumSlackSeconds: number | null;
  usageCount: number;
  pairCount: number;
  diagnostics: string[];
}

interface ResourceUsage {
  id: string;
  cabinId: number;
  visitIndex: number;
  behavior: HeadwayRouteBehavior;
  enterTime: number;
  clearTime: number;
  resourceKey: string;
  resourceId: string;
  rules: HeadwayRule[];
  nodeId: string;
  isInitialBoundary: boolean;
}

export function requiredHeadwaySeconds(
  rule: HeadwayRule,
  leader: HeadwayRouteBehavior,
  follower: HeadwayRouteBehavior,
): number {
  void follower;
  if (rule.kind === "constant") return rule.seconds;
  if (rule.kind === "leader_behavior") {
    return leader === "service" ? rule.service_leader_seconds : rule.bypass_leader_seconds;
  }
  return assertNever(rule);
}

export function checkResourceHeadways({
  artifact,
  movementPlan,
  fleetPlan,
  scenario,
}: {
  artifact: EanBuildArtifact;
  movementPlan: EanMovementPlan;
  fleetPlan: EanFleetPlan | null;
  scenario?: Scenario;
}): ResourceHeadwayCheckResult {
  const policy = artifact.headway_policy;
  if (!policy) {
    return emptyResult("Complete physical headway policy is missing");
  }

  const diagnostics = validatePolicy(policy);
  const ruleById = new Map(policy.rules.map((rule) => [rule.id, rule]));
  const waitingModeByStation = new Map(
    artifact.config.station_configs.map((config) => [config.station_id, config.waiting_mode]),
  );
  const visits = movementPlan.trajectories.flatMap((trajectory) => trajectory.visits);
  const usages: ResourceUsage[] = [];

  for (const resource of policy.resource_requirements) {
    const rule = ruleById.get(resource.rule_id);
    if (!rule) continue;
    const nodeId = resourceNodeId(resource, scenario);
    for (const visit of visits) {
      if (visit.switch_id !== resource.state_id) continue;
      const behavior = behaviorForVisit(visit);
      if (!resourceApplies(resource, behavior)) continue;
      const usage = usageForVisit(
        resource,
        rule,
        visit,
        waitingModeByStation.get(resource.station_id),
        diagnostics,
        nodeId,
      );
      if (usage) usages.push(usage);
    }
  }

  appendInitialBoundaryUsages({
    artifact,
    policy,
    fleetPlan,
    ruleById,
    usages,
    diagnostics,
  });

  const coalescedUsages = coalesceIdenticalUsages(usages);
  const usagesByResource = new Map<string, ResourceUsage[]>();
  for (const usage of coalescedUsages) {
    const group = usagesByResource.get(usage.resourceKey) ?? [];
    group.push(usage);
    usagesByResource.set(usage.resourceKey, group);
  }

  const violations: ReplaySafetyViolation[] = [];
  let totalViolationCount = 0;
  let pairCount = 0;
  let minimumSlackSeconds: number | null = null;
  for (const [resourceKey, group] of usagesByResource) {
    group.sort((left, right) => (
      left.enterTime - right.enterTime
      || left.clearTime - right.clearTime
      || left.cabinId - right.cabinId
      || left.visitIndex - right.visitIndex
    ));
    for (let firstIndex = 0; firstIndex < group.length; firstIndex += 1) {
      const first = group[firstIndex];
      for (let secondIndex = firstIndex + 1; secondIndex < group.length; secondIndex += 1) {
        const second = group[secondIndex];
        pairCount += 1;
        const forwardGap = second.enterTime - first.clearTime;
        const reverseGap = first.enterTime - second.clearTime;
        const forwardRequired = maximumRequiredHeadway(first.rules, first.behavior, second.behavior);
        const reverseRequired = maximumRequiredHeadway(second.rules, second.behavior, first.behavior);
        const forwardSlack = forwardGap - forwardRequired;
        const reverseSlack = reverseGap - reverseRequired;
        const bestSlack = Math.max(forwardSlack, reverseSlack);
        minimumSlackSeconds = minimumSlackSeconds === null
          ? bestSlack
          : Math.min(minimumSlackSeconds, bestSlack);
        // The group is sorted by follower-enter time and the current rule
        // types depend only on the leader. Once this follower is safely after
        // `first`, every later follower is safe after it as well.
        if (bestSlack >= -SAFETY_TOLERANCE_SECONDS) break;

        totalViolationCount += 1;
        if (violations.length >= MAX_STORED_SAFETY_VIOLATIONS) continue;
        const forwardIsCloser = forwardSlack >= reverseSlack;
        const leader = forwardIsCloser ? first : second;
        const follower = forwardIsCloser ? second : first;
        const actual = forwardIsCloser ? forwardGap : reverseGap;
        const required = forwardIsCloser ? forwardRequired : reverseRequired;
        const displayTime = follower.enterTime;
        const conflictStart = Math.min(leader.clearTime, follower.enterTime);
        const conflictEnd = Math.max(leader.clearTime, follower.enterTime);
        violations.push({
          id: `resource:${resourceKey}:${first.id}:${second.id}`,
          kind: first.isInitialBoundary || second.isInitialBoundary
            ? "initial_boundary"
            : "resource_headway",
          cabinIds: [leader.cabinId, follower.cabinId],
          visitIndices: [leader.visitIndex, follower.visitIndex],
          timeSeconds: displayTime,
          activeFromSeconds: Math.max(0, conflictStart - SAFETY_MARKER_WINDOW_SECONDS),
          activeUntilSeconds: Math.min(
            movementPlan.model_end_seconds,
            conflictEnd + SAFETY_MARKER_WINDOW_SECONDS,
          ),
          resourceId: resourceKey,
          ruleId: leader.rules.map((rule) => rule.id).sort().join("+"),
          nodeId: follower.nodeId,
          segmentId: null,
          leaderBehavior: leader.behavior,
          actualSeparation: actual,
          requiredSeparation: required,
          unit: "s",
          message: `${resourceKey}: ${actual.toFixed(3)} s available, ${required.toFixed(3)} s required after a ${leader.behavior} leader`,
        });
      }
    }
  }

  return {
    violations,
    totalViolationCount,
    minimumSlackSeconds,
    usageCount: coalescedUsages.length,
    pairCount,
    diagnostics: unique(diagnostics),
  };
}

function usageForVisit(
  resource: DerivedHeadwayResource,
  rule: HeadwayRule,
  visit: EanVisitPlan,
  waitingMode: string | undefined,
  diagnostics: string[],
  nodeId: string,
): ResourceUsage | null {
  let enterTime: number;
  let clearTime: number;
  if (resource.kind === "platform_entry") {
    if (visit.platform_entry_time_seconds === null) return null;
    enterTime = visit.platform_entry_time_seconds;
    clearTime = enterTime;
  } else if (resource.kind === "platform_exit") {
    if (visit.platform_exit_time_seconds === null) return null;
    if (waitingMode === "station_fifo_buffer") {
      diagnostics.push(`FIFO occupancy trace is unsupported at ${resource.station_id}`);
      return null;
    }
    clearTime = visit.platform_exit_time_seconds;
    enterTime = waitingMode === "end_of_platform_wait"
      ? clearTime - visit.wait_seconds
      : clearTime;
  } else if (resource.kind === "exit_switch" || resource.kind === "service_mechanism") {
    enterTime = visit.exit_switch_time_seconds;
    clearTime = enterTime;
  } else {
    diagnostics.push(`Unsupported resource kind ${(resource as { kind: string }).kind}`);
    return null;
  }
  if (![enterTime, clearTime].every(Number.isFinite) || clearTime < enterTime - SAFETY_TOLERANCE_SECONDS) {
    diagnostics.push(`Invalid usage times for ${resource.id} and cabin ${visit.cabin_id}`);
    return null;
  }
  return {
    id: `visit:${resource.id}:${visit.cabin_id}:${visit.visit_index}`,
    cabinId: visit.cabin_id,
    visitIndex: visit.visit_index,
    behavior: behaviorForVisit(visit),
    enterTime,
    clearTime,
    resourceKey: resource.physical_resource_id
      ? `physical:${resource.physical_resource_id}`
      : resource.id,
    resourceId: resource.id,
    rules: [rule],
    nodeId,
    isInitialBoundary: false,
  };
}

function resourceNodeId(resource: DerivedHeadwayResource, scenario: Scenario | undefined): string {
  if (!scenario || (resource.kind !== "platform_entry" && resource.kind !== "platform_exit")) {
    return resource.exit_switch_id;
  }
  const segmentById = new Map(scenario.track_segments.map((segment) => [segment.id, segment]));
  const serviceRoutes = scenario.station_routes.filter(
    (route) => route.station_id === resource.station_id && route.kind === "service",
  );
  for (const route of serviceRoutes) {
    const segments = route.segment_ids.map((id) => segmentById.get(id)).filter((segment) => segment !== undefined);
    if (segments[0]?.from_node_id !== resource.state_id) continue;
    const platform = segments.find((segment) => segment.kind === "station");
    if (platform) return resource.kind === "platform_entry" ? platform.from_node_id : platform.to_node_id;
  }
  return resource.exit_switch_id;
}

function appendInitialBoundaryUsages({
  artifact,
  policy,
  fleetPlan,
  ruleById,
  usages,
  diagnostics,
}: {
  artifact: EanBuildArtifact;
  policy: DerivedHeadwayPolicy;
  fleetPlan: EanFleetPlan | null;
  ruleById: Map<string, HeadwayRule>;
  usages: ResourceUsage[];
  diagnostics: string[];
}) {
  const fleetMode = artifact.fleet_mode ?? "fixed_starts";
  if (fleetMode !== "optimized_initial_placement") return;
  if (!fleetPlan) {
    diagnostics.push("OIP safety certification requires the exported fleet plan");
    return;
  }
  for (const state of fleetPlan.initial_states) {
    if (state.kind !== "rope") continue;
    const resources = policy.resource_requirements.filter(
      (resource) => (
        resource.state_id === state.switch_id
        && (resource.kind === "exit_switch" || resource.kind === "service_mechanism")
      ),
    );
    const needsPreviousBehavior = resources.some((resource) => {
      const rule = ruleById.get(resource.rule_id);
      return resource.kind === "service_mechanism" || rule?.kind === "leader_behavior";
    });
    if (needsPreviousBehavior && state.previous_service === null) {
      diagnostics.push(`Initial rope state for cabin ${state.cabin_id} lacks previous_service`);
      continue;
    }
    const behavior: HeadwayRouteBehavior = state.previous_service ? "service" : "bypass";
    for (const resource of resources) {
      if (!resourceApplies(resource, behavior)) continue;
      const rule = ruleById.get(resource.rule_id);
      if (!rule) continue;
      usages.push({
        id: `boundary:${resource.id}:${state.cabin_id}:${state.visit_index}`,
        cabinId: state.cabin_id,
        visitIndex: state.visit_index - 1,
        behavior,
        enterTime: state.previous_event_time_seconds,
        clearTime: state.previous_event_time_seconds,
        resourceKey: resource.physical_resource_id
          ? `physical:${resource.physical_resource_id}`
          : resource.id,
        resourceId: resource.id,
        rules: [rule],
        nodeId: resource.exit_switch_id,
        isInitialBoundary: true,
      });
    }
  }
}

function maximumRequiredHeadway(
  rules: HeadwayRule[],
  leader: HeadwayRouteBehavior,
  follower: HeadwayRouteBehavior,
): number {
  return Math.max(...rules.map((rule) => requiredHeadwaySeconds(rule, leader, follower)));
}

function coalesceIdenticalUsages(usages: ResourceUsage[]): ResourceUsage[] {
  const byIdentity = new Map<string, ResourceUsage>();
  for (const usage of usages) {
    const identity = [
      usage.resourceKey,
      usage.cabinId,
      usage.visitIndex,
      usage.behavior,
      usage.enterTime,
      usage.clearTime,
      usage.isInitialBoundary ? "boundary" : "regular",
    ].join("|");
    const existing = byIdentity.get(identity);
    if (!existing) {
      byIdentity.set(identity, usage);
      continue;
    }
    const rulesById = new Map(
      [...existing.rules, ...usage.rules].map((rule) => [rule.id, rule]),
    );
    byIdentity.set(identity, {
      ...existing,
      id: [existing.id, usage.id].sort().join("+"),
      resourceId: [existing.resourceId, usage.resourceId].sort().join("+"),
      rules: [...rulesById.values()].sort((left, right) => left.id.localeCompare(right.id)),
    });
  }
  return [...byIdentity.values()];
}

function validatePolicy(policy: DerivedHeadwayPolicy): string[] {
  const diagnostics: string[] = [];
  const ruleIds = new Set<string>();
  for (const rule of policy.rules) {
    if (!rule.id || ruleIds.has(rule.id)) diagnostics.push(`Duplicate or empty rule ID ${rule.id}`);
    ruleIds.add(rule.id);
    const values = rule.kind === "constant"
      ? [rule.seconds]
      : rule.kind === "leader_behavior"
        ? [rule.bypass_leader_seconds, rule.service_leader_seconds]
        : [];
    if (values.length === 0 || values.some((value) => !Number.isFinite(value) || value <= 0)) {
      diagnostics.push(`Invalid or unsupported headway rule ${rule.id}`);
    }
  }
  const resourceIds = new Set<string>();
  for (const resource of policy.resource_requirements) {
    if (!resource.id || resourceIds.has(resource.id)) diagnostics.push(`Duplicate or empty resource ID ${resource.id}`);
    resourceIds.add(resource.id);
    if (!ruleIds.has(resource.rule_id)) diagnostics.push(`Resource ${resource.id} references missing rule ${resource.rule_id}`);
  }
  return diagnostics;
}

function resourceApplies(
  resource: DerivedHeadwayResource,
  behavior: HeadwayRouteBehavior,
): boolean {
  return behavior === "service" ? resource.applies_to_service : resource.applies_to_bypass;
}

function behaviorForVisit(visit: EanVisitPlan): HeadwayRouteBehavior {
  return visit.decision === "stop" ? "service" : "bypass";
}

function emptyResult(diagnostic: string): ResourceHeadwayCheckResult {
  return {
    violations: [],
    totalViolationCount: 0,
    minimumSlackSeconds: null,
    usageCount: 0,
    pairCount: 0,
    diagnostics: [diagnostic],
  };
}

function unique(values: string[]) {
  return [...new Set(values)];
}

function assertNever(value: never): never {
  throw new Error(`Unsupported headway rule: ${JSON.stringify(value)}`);
}
