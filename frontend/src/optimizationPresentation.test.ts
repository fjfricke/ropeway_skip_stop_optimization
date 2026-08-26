import { describe, expect, it } from "vitest";

import {
  formatOptimizationNumber,
  formatOptimizationDuration,
  formatOptimizationMemory,
  optimizationSemanticStatus,
  optimizationStatusClass,
} from "./optimizationPresentation";

describe("optimization result presentation", () => {
  it("does not turn a missing upper bound into zero", () => {
    expect(formatOptimizationNumber(null, 2)).toBe("—");
    expect(formatOptimizationNumber(undefined, 2)).toBe("—");
  });

  it("formats solver duration and worker memory compactly", () => {
    expect(formatOptimizationDuration(50.5)).toBe("50.5s");
    expect(formatOptimizationDuration(125)).toBe("2m 5s");
    expect(formatOptimizationMemory(590_512_128)).toBe("563 MiB");
  });

  it("shows the mathematical solver status after a completed run", () => {
    const status = optimizationSemanticStatus({
      trial_id: "trial",
      policy_id: "skip_stop",
      available_fleet_count: 20,
      status: "complete",
      solver_status: "unknown_no_incumbent",
      events: [],
    });

    expect(status).toBe("unknown_no_incumbent");
    expect(optimizationStatusClass(status)).toBe("unknown");
  });
});
