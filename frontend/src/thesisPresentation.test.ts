import { describe, expect, it } from "vitest";
import { bestRun, groupRuns, matchingAllStop, plannedThesisGroups, referenceLabel } from "./thesisPresentation";
import type { ThesisIndex } from "./thesisTypes";

describe("thesis presentation", () => {
  it("matches All-Stop only for the same full comparison contract", () => {
    const run = { id: "ss", groupId: "g", method: "labelled_arc_flow" as const, status: "complete" as const,
      operatingMode: "skip_stop" as const, k: 10, demand: 150, releaseResolutionSeconds: 15, caseFingerprint: "domain", validated: true };
    const as = { ...run, id: "as", operatingMode: "all_stop" as const };
    expect(matchingAllStop(run, [as])?.id).toBe("as");
    expect(matchingAllStop(run, [{ ...as, k: 11 }])).toBeUndefined();
    expect(matchingAllStop(run, [{ ...as, releaseResolutionSeconds: 30 }])).toBeUndefined();
    expect(matchingAllStop(run, [{ ...as, caseFingerprint: "different" }])).toBeUndefined();
  });
  it("contains the frozen twelve-group G500 matrix", () => {
    expect(plannedThesisGroups).toHaveLength(12);
    expect(new Set(plannedThesisGroups.map((group) => group.id)).size).toBe(12);
    expect(plannedThesisGroups.filter((group) => group.objective === "unserved")).toHaveLength(8);
    expect(plannedThesisGroups.filter((group) => group.objective === "journey_time")).toHaveLength(4);
  });

  it("does not render an open capacity interval as an exact maximum", () => {
    const group = { ...plannedThesisGroups[0], reference: {
      provenFeasibleDemand: 2800,
      provenInfeasibleDemand: 2900,
      capacityProven: false,
    } };
    expect(referenceLabel(group)).toBe("2,800 ≤ κAS < 2,900");
  });

  it("selects only validated completed results", () => {
    const group = { ...plannedThesisGroups[0], runIds: ["reference", "a", "b", "c"] };
    const index: ThesisIndex = {
      schema: "thesis_frontend_index_v1", campaignStatus: "ready", groups: [group], runs: [
        { id: "reference", groupId: group.id, status: "complete", method: "all_stop_phase", served: 1000 },
        { id: "a", groupId: group.id, status: "complete", method: "evolution", served: 100 },
        { id: "b", groupId: group.id, status: "complete", method: "evolution", served: 120 },
        { id: "c", groupId: group.id, status: "unknown", method: "evolution", served: 200 },
      ],
    };
    const runs = groupRuns(index, group);
    expect(bestRun(runs, "unserved")?.id).toBe("b");
  });

  it("prefers the smaller fleet when service is tied", () => {
    const runs = [
      { id: "k76", groupId: "g", status: "complete" as const, method: "evolution" as const, served: 3226, k: 76 },
      { id: "k75", groupId: "g", status: "complete" as const, method: "evolution" as const, served: 3226, k: 75 },
    ];
    expect(bestRun(runs, "unserved")?.id).toBe("k75");
  });

  it("does not compare served counts across different demands", () => {
    const runs = [
      { id: "a", groupId: "g", status: "complete" as const, method: "evolution" as const, served: 100, demand: 100 },
      { id: "b", groupId: "g", status: "complete" as const, method: "evolution" as const, served: 110, demand: 150 },
    ];
    expect(bestRun(runs, "unserved")).toBeUndefined();
  });
});
