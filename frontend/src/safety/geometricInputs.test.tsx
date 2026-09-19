import { expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { Scenario, EanBuildArtifact, EanMovementPlan, EanPhysicalReplay } from "../types";
import { ParametersPanel } from "../components/ParametersPanel";
import { validateSafetyInputs } from "./decodeSafetyInputs";

const scenario = {
  scenario_id: "geometric", physical_nodes: [], track_segments: [], station_routes: [],
  demands: [], operating: { cabin_length_m: 3, min_clearance_m: 0.5,
    rope_speed_m_per_s: 6, station_speed_m_per_s: 0.3, cabin_capacity: 10 },
  headway_design: { schema_version: 2, physical: {
    service_clearance_m: 0.5, rope_clearance_m: 0.5, cabin_height_m: 2.22,
    attachment_to_cabin_roof_m: 2, rope_sway_angle_rad: 0.34, provenance: [],
  }, station_mechanisms: [{ exit_switch_id: "exit", design: {} }], provenance: [] },
} as unknown as Scenario;

function diagnostics(input: Scenario) {
  return validateSafetyInputs({ scenario: input,
    artifact: { safety_schema_version: "frontend_replay_safety_v1" } as EanBuildArtifact,
    movementPlan: { model_end_seconds: 10, trajectories: [] } as unknown as EanMovementPlan,
    fleetPlan: null,
    replay: { model_end_seconds: 10, events: [] } as unknown as EanPhysicalReplay,
  }).filter(s => /parameter/i.test(s));
}

it("accepts geometric parameters without fault inputs and hides absent mechanisms", () => {
  expect(diagnostics(scenario)).toEqual([]);
  const html = renderToStaticMarkup(<ParametersPanel scenario={scenario} />);
  expect(html).not.toContain("station mechanism");
  expect(html).toContain("geometric entry / exit headway");
  expect(html).toContain("1.052 s");
  expect(html).toContain("11.667 s");
});

it("keeps old fault inputs readable and validates a migrated fault mechanism", () => {
  const old = structuredClone(scenario);
  const design = old.headway_design!;
  delete design.schema_version;
  Object.assign(design.physical, { merge_clearance_m: 0.5, control_delay_seconds: 0.5,
    emergency_merge_sway_angle_rad: 0.34, emergency_deceleration_m_per_s2: 1.75 });
  design.station_mechanisms[0].design = { mechanical_service_cycle_seconds: 6, service_resource_id: "attachment" };
  expect(diagnostics(old)).toEqual([]);
  expect(renderToStaticMarkup(<ParametersPanel scenario={old} />)).toContain("station mechanism");
  design.schema_version = 2;
  expect(diagnostics(old)).toContain("Missing legacy mechanism parameter emergency_deceleration_m_per_s2");
  Object.assign(design.station_mechanisms[0].design, { merge_clearance_m: 0.5,
    control_delay_seconds: 0.5, emergency_merge_sway_angle_rad: 0.34,
    emergency_deceleration_m_per_s2: 1.75 });
  expect(diagnostics(old)).toEqual([]);
});
