import { readFileSync } from "node:fs";
import type {
  EanBuildArtifact,
  EanMovementPlan,
  EanPhysicalReplay,
  Scenario,
} from "../src/types";
import { certifyReplaySafety } from "../src/safety";

const [scenarioPath, artifactPath, movementPlanPath, replayPath] = process.argv.slice(2);
if (!scenarioPath || !artifactPath || !movementPlanPath || !replayPath) {
  throw new Error("Usage: checkReplaySafety <scenario.json> <ean-artifact.json> <movement-plan.json> <replay.json>");
}

const scenario = read<Scenario>(scenarioPath);
const artifact = read<EanBuildArtifact>(artifactPath);
const movementPlan = read<EanMovementPlan>(movementPlanPath);
const replay = read<EanPhysicalReplay>(replayPath);
const report = certifyReplaySafety({
  scenario,
  artifact,
  movementPlan,
  fleetPlan: movementPlan.fleet_plan ?? null,
  replay,
});

process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
process.exitCode = report.status === "safe" ? 0 : report.status === "unsafe" ? 1 : 2;

function read<T>(path: string): T {
  return JSON.parse(readFileSync(path, "utf8")) as T;
}
