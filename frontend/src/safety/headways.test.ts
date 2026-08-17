import { describe, expect, it } from "vitest";
import type {
  DerivedHeadwayPolicy,
  EanBuildArtifact,
  EanMovementPlan,
  EanVisitPlan,
  HeadwayRule,
} from "../types";
import { checkResourceHeadways, requiredHeadwaySeconds } from "./headways";

describe("directed headway rules", () => {
  const rule: HeadwayRule = {
    id: "merge-b",
    kind: "leader_behavior",
    bypass_leader_seconds: 2,
    service_leader_seconds: 5,
  };

  it("depends on the leader and not the follower", () => {
    expect(requiredHeadwaySeconds(rule, "bypass", "bypass")).toBe(2);
    expect(requiredHeadwaySeconds(rule, "bypass", "service")).toBe(2);
    expect(requiredHeadwaySeconds(rule, "service", "bypass")).toBe(5);
    expect(requiredHeadwaySeconds(rule, "service", "service")).toBe(5);
  });

  it("detects a service-leader violation while accepting a bypass leader", () => {
    const serviceResult = checkResourceHeadways({
      artifact: artifact(policy(rule)),
      movementPlan: plan([visit(0, 0, "stop", 10), visit(1, 0, "skip", 14)]),
      fleetPlan: null,
    });
    expect(serviceResult.totalViolationCount).toBe(1);
    expect(serviceResult.minimumSlackSeconds).toBeCloseTo(-1);

    const bypassResult = checkResourceHeadways({
      artifact: artifact(policy(rule)),
      movementPlan: plan([visit(0, 0, "skip", 10), visit(1, 0, "stop", 14)]),
      fleetPlan: null,
    });
    expect(bypassResult.totalViolationCount).toBe(0);
    expect(bypassResult.minimumSlackSeconds).toBeCloseTo(2);
  });

  it("checks two rotations of the same cabin", () => {
    const result = checkResourceHeadways({
      artifact: artifact(policy({ id: "constant", kind: "constant", seconds: 3 })),
      movementPlan: plan([visit(0, 0, "stop", 10), visit(0, 1, "stop", 12)]),
      fleetPlan: null,
    });
    expect(result.totalViolationCount).toBe(1);
  });

  it.each([
    [12.999, 1],
    [13, 0],
    [13.001, 0],
  ])("handles a constant threshold at event time %s", (eventTime, expectedViolations) => {
    const result = checkResourceHeadways({
      artifact: artifact(policy({ id: "constant", kind: "constant", seconds: 3 })),
      movementPlan: plan([visit(0, 0, "stop", 10), visit(1, 0, "stop", eventTime)]),
      fleetPlan: null,
    });
    expect(result.totalViolationCount).toBe(expectedViolations);
  });

  it("checks C's service recovery independently of its main-rope rule", () => {
    const architectureC = policy({ id: "rope", kind: "constant", seconds: 1 });
    architectureC.rules.push({ id: "recovery", kind: "constant", seconds: 6 });
    architectureC.resource_requirements.push({
      id: "recovery",
      state_id: "S_entry",
      exit_switch_id: "S_exit",
      station_id: "S",
      kind: "service_mechanism",
      rule_id: "recovery",
      applies_to_service: true,
      applies_to_bypass: false,
      physical_resource_id: "recovery",
    });
    const serviceResult = checkResourceHeadways({
      artifact: artifact(architectureC),
      movementPlan: plan([visit(0, 0, "stop", 10), visit(1, 0, "stop", 15)]),
      fleetPlan: null,
    });
    expect(serviceResult.totalViolationCount).toBe(1);

    const bypassResult = checkResourceHeadways({
      artifact: artifact(architectureC),
      movementPlan: plan([visit(0, 0, "skip", 10), visit(1, 0, "skip", 15)]),
      fleetPlan: null,
    });
    expect(bypassResult.totalViolationCount).toBe(0);
  });

  it("coalesces identical aliases of a physical resource and uses the stronger rule", () => {
    const basePolicy = policy({ id: "weak", kind: "constant", seconds: 2 });
    basePolicy.rules.push({ id: "strong", kind: "constant", seconds: 5 });
    basePolicy.resource_requirements.push({
      ...basePolicy.resource_requirements[0],
      id: "merge-alias",
      rule_id: "strong",
    });
    const result = checkResourceHeadways({
      artifact: artifact(basePolicy),
      movementPlan: plan([visit(0, 0, "stop", 10), visit(1, 0, "stop", 14)]),
      fleetPlan: null,
    });
    expect(result.usageCount).toBe(2);
    expect(result.pairCount).toBe(1);
    expect(result.totalViolationCount).toBe(1);
  });

  it("uses the occupied waiting interval at a platform exit", () => {
    const physicalPolicy = policy({ id: "platform", kind: "constant", seconds: 2 }, "platform_exit");
    const first = visit(0, 0, "stop", 10);
    const second = { ...visit(1, 0, "stop", 15), wait_seconds: 4 };
    const result = checkResourceHeadways({
      artifact: artifact(physicalPolicy, "end_of_platform_wait"),
      movementPlan: plan([first, second]),
      fleetPlan: null,
    });
    expect(result.totalViolationCount).toBe(1);
    expect(result.minimumSlackSeconds).toBeCloseTo(-1);
  });

  it("fails closed for FIFO waiting without a position trace", () => {
    const result = checkResourceHeadways({
      artifact: artifact(
        policy({ id: "platform", kind: "constant", seconds: 2 }, "platform_exit"),
        "station_fifo_buffer",
      ),
      movementPlan: plan([visit(0, 0, "stop", 10), visit(1, 0, "stop", 15)]),
      fleetPlan: null,
    });
    expect(result.diagnostics).toContain("FIFO occupancy trace is unsupported at S");
  });

  it("checks the OIP event immediately before the visible horizon", () => {
    const oipArtifact = artifact(policy(rule));
    oipArtifact.fleet_mode = "optimized_initial_placement";
    const result = checkResourceHeadways({
      artifact: oipArtifact,
      movementPlan: plan([visit(1, 0, "skip", 4)]),
      fleetPlan: {
        mode: "optimized_initial_placement",
        available_fleet_count: 2,
        active_cabin_ids: [0, 1],
        inactive_cabin_ids: [],
        initial_states: [{
          cabin_id: 0,
          kind: "rope",
          switch_id: "S_entry",
          visit_index: 0,
          progress: 0.5,
          previous_event_time_seconds: 0,
          next_event_time_seconds: 8,
          previous_service: true,
        }],
      },
    });
    expect(result.totalViolationCount).toBe(1);
    expect(result.violations[0].kind).toBe("initial_boundary");
  });

  it("fails closed when architecture B lacks OIP predecessor behavior", () => {
    const oipArtifact = artifact(policy(rule));
    oipArtifact.fleet_mode = "optimized_initial_placement";
    const result = checkResourceHeadways({
      artifact: oipArtifact,
      movementPlan: plan([visit(1, 0, "skip", 8)]),
      fleetPlan: {
        mode: "optimized_initial_placement",
        available_fleet_count: 2,
        active_cabin_ids: [0, 1],
        inactive_cabin_ids: [],
        initial_states: [{
          cabin_id: 0,
          kind: "rope",
          switch_id: "S_entry",
          visit_index: 0,
          progress: 0.5,
          previous_event_time_seconds: 0,
          next_event_time_seconds: 8,
          previous_service: null,
        }],
      },
    });
    expect(result.diagnostics).toContain("Initial rope state for cabin 0 lacks previous_service");
  });
});

function policy(rule: HeadwayRule, kind: "exit_switch" | "platform_exit" = "exit_switch"): DerivedHeadwayPolicy {
  return {
    rules: [rule],
    resource_requirements: [{
      id: "merge",
      state_id: "S_entry",
      exit_switch_id: "S_exit",
      station_id: "S",
      kind,
      rule_id: rule.id,
      applies_to_service: true,
      applies_to_bypass: true,
      physical_resource_id: "shared-merge",
    }],
    spatial_spacings: [],
    derived_quantities: [],
    provenance: [],
    legacy: false,
  };
}

function artifact(
  headwayPolicy: DerivedHeadwayPolicy,
  waitingMode: "no_waiting" | "end_of_platform_wait" | "station_fifo_buffer" = "no_waiting",
): EanBuildArtifact {
  return {
    scenario_id: "test",
    config: {
      horizon_seconds: 20,
      tail_seconds: 0,
      station_configs: [{ station_id: "S", waiting_mode: waitingMode, fifo_capacity: null, max_wait_seconds: null }],
    },
    headway_policy: headwayPolicy,
    switch_cycle: [],
    timings: [],
    cabin_starts: [],
    switch_visits: [],
    switch_transitions: [],
    headway_checkpoints: [],
    headway_candidates: [],
    headway_pairs: [],
  } as unknown as EanBuildArtifact;
}

function visit(
  cabinId: number,
  visitIndex: number,
  decision: "stop" | "skip",
  eventTime: number,
): EanVisitPlan {
  return {
    cabin_id: cabinId,
    visit_index: visitIndex,
    switch_id: "S_entry",
    station_id: "S",
    decision,
    switch_time_seconds: eventTime - 2,
    platform_entry_time_seconds: decision === "stop" ? eventTime - 1 : null,
    platform_exit_time_seconds: decision === "stop" ? eventTime : null,
    exit_switch_time_seconds: eventTime,
    next_switch_time_seconds: 20,
    wait_seconds: 0,
  };
}

function plan(visits: EanVisitPlan[]): EanMovementPlan {
  const byCabin = new Map<number, EanVisitPlan[]>();
  for (const item of visits) byCabin.set(item.cabin_id, [...(byCabin.get(item.cabin_id) ?? []), item]);
  return {
    scenario_id: "test",
    horizon_seconds: 20,
    model_end_seconds: 20,
    horizon_formulation: "horizon_exact_time_activation",
    trajectories: [...byCabin].map(([cabin_id, cabinVisits]) => ({ cabin_id, visits: cabinVisits })),
  };
}
