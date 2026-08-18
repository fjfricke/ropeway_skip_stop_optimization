import { describe, expect, it } from "vitest";
import type { DerivedHeadwayPolicy, EanMovementPlan, EanPhysicalReplay, Scenario } from "../types";
import { validateSpatialPolicyAgainstScenario } from "./decodeSafetyInputs";
import { checkContinuousSpacing } from "./geometry";

describe("continuous physical spacing", () => {
  it("finds a collision between ordinary rendered frames", () => {
    const result = checkContinuousSpacing({
      scenario: scenario(),
      policy: policy(),
      movementPlan: movementPlan(),
      replay: replay(),
    });
    expect(result.diagnostics).toEqual([]);
    expect(result.totalViolationCount).toBe(1);
    expect(result.violations[0].timeSeconds).toBeCloseTo(5);
    expect(result.violations[0].actualSeparation).toBeCloseTo(0);
    expect(result.violations[0].requiredSeparation).toBe(2);
  });

  it("minimizes linear-speed motion continuously", () => {
    const linearScenario = scenario();
    linearScenario.track_segments[0].speed_profile = {
      kind: "linear",
      speed_m_per_s: null,
      start_speed_m_per_s: 0,
      end_speed_m_per_s: 2,
    };
    const result = checkContinuousSpacing({
      scenario: linearScenario,
      policy: policy(),
      movementPlan: movementPlan(),
      replay: replay(),
    });
    expect(result.totalViolationCount).toBe(1);
    expect(result.violations[0].timeSeconds).toBeCloseTo(Math.sqrt(50), 6);
    expect(result.violations[0].actualSeparation).toBeCloseTo(0, 6);
  });

  it("uses the exported physical rope envelope instead of legacy operating spacing", () => {
    const physicalRopeSpacingM = 3 + 2 * 4.22 * Math.sin(0.34) + 0.5;
    const shiftedReplay: EanPhysicalReplay = {
      ...replay(),
      events: [
        event(0, 0, "A", []),
        event(0, 10, "B", ["rope"]),
        event(1, -5.6, "A", []),
        event(1, 4.4, "B", ["rope"]),
      ],
    };
    const physicalPolicy = policy();
    physicalPolicy.spatial_spacings[0].spacing_m = physicalRopeSpacingM;

    const physicalResult = checkContinuousSpacing({
      scenario: scenario(),
      policy: physicalPolicy,
      movementPlan: movementPlan(),
      replay: shiftedReplay,
    });
    expect(physicalResult.totalViolationCount).toBe(1);
    expect(physicalResult.violations[0].actualSeparation).toBeCloseTo(5.6);
    expect(physicalResult.violations[0].requiredSeparation).toBeCloseTo(6.314631);

    const legacyResult = checkContinuousSpacing({
      scenario: scenario(),
      policy: policy(),
      movementPlan: movementPlan(),
      replay: shiftedReplay,
    });
    expect(legacyResult.totalViolationCount).toBe(0);
  });

  it("rejects a stale spatial policy after the carrier geometry changes", () => {
    const physicalScenario = scenario();
    physicalScenario.operating.cabin_length_m = 3;
    physicalScenario.headway_design = {
      physical: {
        service_clearance_m: 0.5,
        rope_clearance_m: 0.5,
        merge_clearance_m: 0.5,
        cabin_height_m: 2.22,
        attachment_to_cabin_roof_m: 2,
        rope_sway_angle_rad: 0.34,
        emergency_merge_sway_angle_rad: 0.34,
        control_delay_seconds: 0.5,
        emergency_deceleration_m_per_s2: 1.75,
        provenance: [],
      },
      station_mechanisms: [],
      provenance: [],
    };
    const currentPolicy = policy();
    currentPolicy.spatial_spacings = [
      { role: "rope", spacing_m: 3 + 2 * 4.22 * Math.sin(0.34) + 0.5 },
      { role: "service", spacing_m: 3.5 },
    ];
    expect(validateSpatialPolicyAgainstScenario(physicalScenario, currentPolicy)).toEqual([]);

    currentPolicy.spatial_spacings[0].spacing_m = 5.500922552844886;
    expect(validateSpatialPolicyAgainstScenario(physicalScenario, currentPolicy)).toEqual([
      "rope spatial spacing 5.500922552844886 m is inconsistent with scenario geometry 6.314631057668474 m",
    ]);
  });
});

function scenario(): Scenario {
  return {
    scenario_id: "geometry",
    service_start_time: "08:00:00",
    service_end_time: "08:00:10",
    stations: [],
    physical_nodes: [
      { id: "A", kind: "connector", station_id: null, allows_waiting: false },
      { id: "B", kind: "connector", station_id: null, allows_waiting: false },
    ],
    track_segments: [{
      id: "rope",
      kind: "rope",
      from_node_id: "A",
      to_node_id: "B",
      length_m: 10,
      speed_profile: { kind: "constant", speed_m_per_s: 1, start_speed_m_per_s: null, end_speed_m_per_s: null },
      resource_id: "rope",
    }],
    station_routes: [],
    cabins: [{ id: 0 }, { id: 1 }],
    cabin_initial_states: [],
    demands: [],
    operating: {
      rope_speed_m_per_s: 1,
      station_speed_m_per_s: 1,
      cabin_capacity: 10,
      cabin_length_m: 1,
      min_clearance_m: 1,
    },
  };
}

function policy(): DerivedHeadwayPolicy {
  return {
    rules: [],
    resource_requirements: [],
    spatial_spacings: [
      { role: "rope", spacing_m: 2 },
      { role: "service", spacing_m: 2 },
    ],
    derived_quantities: [],
    provenance: [],
    legacy: false,
  };
}

function movementPlan(): EanMovementPlan {
  return {
    scenario_id: "geometry",
    horizon_seconds: 10,
    model_end_seconds: 10,
    horizon_formulation: "horizon_exact_time_activation",
    trajectories: [0, 1].map((cabin_id) => ({
      cabin_id,
      visits: [{
        cabin_id,
        visit_index: 0,
        switch_id: cabin_id === 0 ? "A" : "B",
        station_id: "none",
        decision: "skip",
        switch_time_seconds: 0,
        platform_entry_time_seconds: null,
        platform_exit_time_seconds: null,
        exit_switch_time_seconds: 0,
        next_switch_time_seconds: 10,
        wait_seconds: 0,
      }],
    })),
  };
}

function replay(): EanPhysicalReplay {
  return {
    scenario_id: "geometry",
    horizon_seconds: 10,
    model_end_seconds: 10,
    events: [
      event(0, 0, "A", []),
      event(0, 10, "B", ["rope"]),
      event(1, 0, "B", []),
      event(1, 10, "A", ["rope"]),
    ],
  };
}

function event(cabin_id: number, time_seconds: number, physical_node_id: string, source_segment_ids: string[]) {
  return {
    cabin_id,
    visit_index: 0,
    event_kind: time_seconds === 0 ? "exit_switch" as const : "reach_next_switch" as const,
    time_seconds,
    switch_id: physical_node_id,
    station_id: "none",
    physical_node_id,
    source_segment_ids,
  };
}
